#===============================================================================
#
# Copyright (c) 2014 Qualcomm Technologies, Inc. All Rights Reserved.
# Qualcomm Technologies Proprietary and Confidential.
#
#===============================================================================

'''
Created on Feb 3, 2014

@author: yliong
'''
from base_signer import BaseSigner
from cass.signaturepackage import SignaturePackage
from cass.signingpackage import SigningPackage
import sectools.features.isc.secimage as secimage
import binascii
from sectools.common.utils.c_logging import logger
import signerutils
from sectools.common.utils import c_path
from certificate import Certificate
import os
from cass.cassconnector import CassConnector
from signer_error import ExternalSignerError
from config_error import ConfigError
import shutil

class CassSigner(BaseSigner):
    '''
    classdocs
    '''
    CASS_SIGNATTR_USE_EXP3 = "EXP_3"
    SIGNINGPACKAGE_FILENAME = "signingpackage.xml"

    MESG_INVALID_SIG = "CASS Signer selected. Signature validation failed for {0} \n"
    MESG_SIG_NOT_FOUND = "CASS Signer selected. Signature output not found in {0} \n"
    MESG_MISSING_CASS_CONFIG = "CASS Signer selected. Cass signer attributes are missing in the user config file.\n"

    def __init__(self, config):
        '''
        Constructor
        '''
        self.config = config

    def sign(self, hash_to_sign, imageinfo, binary_to_sign = None):
        cass_signer_attributes = self.config.signing.signer_attributes.cass_signer_attributes
        self._validate_config(cass_signer_attributes)

        signingpackage_fname = os.path.join(imageinfo.dest_image.image_dir, self.SIGNINGPACKAGE_FILENAME)
        signing_package = self._generate_signing_package(hash_to_sign,
                      imageinfo.signing_attributes,
                      cass_signer_attributes,
                      imageinfo.dest_image.image_path,
                      signingpackage_fname,
                      binary_to_sign
                      )

        cert_folder = imageinfo.dest_image.cert_folder
        connector = CassConnector(cass_signer_attributes)
        signature_package_blob = connector.sign(signingpackage_fname, imageinfo.dest_image.image_dir)
        self._process_signature_package(signature_package_blob, signing_package, cert_folder)

        sig_package = signerutils.getSigPackage(cert_folder)
        if sig_package is not None:
            [signature, cert_chain_list] = signerutils.\
                                        readSigFromZip(sig_package)
            if self.validate_sig(binary_to_sign, signature,
                                        cert_chain_list) is False:
                raise ExternalSignerError(
                        self.MESG_INVALID_SIG.format(sig_package))
        else:
            raise ExternalSignerError(
                    self.MESG_SIG_NOT_FOUND.
                                format(cert_folder))
        signer_output = self._get_signer_output(signature, cert_chain_list)

        self._cleanup(cert_folder)

        return signer_output

    def _generate_signing_package(self, hash_to_sign, signing_attributes, cass_signer_attributes,
                                image_path, signingpackage_fname, binary_to_sign):

        signingpackage = SigningPackage(secimage.__version__)
        signingrequest = signingpackage.createSigningRequest("image_to_sign=%s" % image_path)

        hexbindigest = binascii.b2a_hex(hash_to_sign)
        logger.debug("Digest to sign (hexbinary)= [%s]" % hexbindigest)
        signingrequest.setDigest(hexbindigest)
        signingrequest.setCapability(cass_signer_attributes.capability)
        signingrequest.setSigningAttribute(Certificate.SIGNATTR_SW_SIZE, "0x%.8X" % len(binary_to_sign))

        hmac_params = signerutils.get_hmac_params_from_config(signing_attributes)
        signingrequest.setSigningAttribute(Certificate.SIGNATTR_HW_ID, "0x%s" % hmac_params.msm_id_str)
        signingrequest.setSigningAttribute(Certificate.SIGNATTR_SW_ID, signing_attributes.sw_id)
        signingrequest.setSigningAttribute(Certificate.SIGNATTR_MODEL_ID, signing_attributes.model_id)
        signingrequest.setSigningAttribute(Certificate.SIGNATTR_OEM_ID, signing_attributes.oem_id)
        if signing_attributes.debug:
            signingrequest.setSigningAttribute(Certificate.SIGNATTR_DEBUG, signing_attributes.debug)
        if signing_attributes.app_id:
            signingrequest.setSigningAttribute(Certificate.SIGNATTR_APP_ID, signing_attributes.app_id)
        if signing_attributes.crash_dump:
            signingrequest.setSigningAttribute(Certificate.SIGNATTR_CRASH_DUMP, signing_attributes.crash_dump)
        if signing_attributes.exponent == 3:
            signingrequest.setSigningAttribute(self.CASS_SIGNATTR_USE_EXP3, 'TRUE')
        elif signing_attributes.exponent == 65537:
            signingrequest.setSigningAttribute(self.CASS_SIGNATTR_USE_EXP3, 'FALSE')
        else:
            raise RuntimeError, "Exponent value of {0} is invalid!".format(signing_attributes.exponent)

        # Set signature algorithm to SHA256 by default
        signingrequest.setSigningAttribute(Certificate.SIGNATTR_SHA256, 'TRUE')

        pathname, fname = os.path.split(signingpackage_fname)
        c_path.create_dir(pathname)

        signingpackage.toxml()
        signingpackage.saveToFile(signingpackage_fname)
        logger.info("Signing package created. Digest = [%s]" % signingpackage.getDigest())
        return signingpackage

    def _process_signature_package(self, signaturepackage, signingpackage, cert_dir):
        signaturePackage = SignaturePackage(signaturepackage)
        logger.debug("Signing package digest from Signature Package = [%s]" % signaturePackage.getSPDigest())
        if (signaturePackage.getSPDigest().lower() != signingpackage.getDigest().lower()):
            raise ExternalSignerError, "Signing Package Digest mismatched from Signature Package!"

        if signaturePackage.getCount() == 1:
            signatureResponse = signaturePackage.getSignatureResponse(1)
        else:
            raise ExternalSignerError, "Signature Package has unexpected count = %d!" % signaturePackage.getCount()

        statusCode = signatureResponse.getStatusCode()
        logger.debug("Status returned from Signature Response: %s" % statusCode)
        if statusCode == "1":
            signatureResponse.saveResultToDir(cert_dir)
        else:
            raise ExternalSignerError, "Error returned from Signature Response:\n%s" % signatureResponse.getError()

    def _validate_config(self, cass_signer_attributes):
        if not cass_signer_attributes:
            raise ConfigError(self.MESG_MISSING_CASS_CONFIG)

    def _cleanup(self, cert_folder):
        if os.path.exists(cert_folder):
            shutil.rmtree(cert_folder)


