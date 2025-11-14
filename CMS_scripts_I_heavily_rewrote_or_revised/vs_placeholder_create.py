#!/usr/bin/python3
# script version and log level
script_version = "250203.19"
log_level = "INFO" # DEBUG INFO WARN ERROR
'''
ARGUMENTS RECEIVED FROM VANTAGE:
1. VS Metadata XML
2. Environment

WHAT THIS SCRIPT DOES:
-Gets Vault secrets
-Sends POST call to create placeholder item, with metadata values specified in the metadata values provided by argument #1
    -Metadata doc is constructed in Vantage; otherwise this script would need 16 arguments instead of 2
-Returns placeholder item ID
'''
###CHANGE LOG###
'''
version 250203.19 - initial version
'''

# native imports
import sys, requests, traceback
from requests.exceptions import HTTPError
import xml.etree.ElementTree as ET

# custom support packages live in the scripts/packages/ directory
# add path to packages for import
script_path = sys.argv[0]
if 'linux' in sys.platform or 'darwin' in sys.platform:
    packages_path = script_path[:script_path.rfind('/scripts/')]+'/packages/'
else:
    packages_path = script_path[:script_path.rfind('\\scripts\\')]+'\\packages\\'
sys.path.insert(0,packages_path)

# add variable for path to crt_file (DigiCertCA.crt) which is in the packages path above
crt_file = packages_path + 'DigiCertCA.crt'

# import logging module
import cms_integration_logging # need this for everything

# args to variables
script_name =  cms_integration_logging.get_script_name(sys.argv[0])
arg_problem = False
if len(sys.argv) == 3:
    metadata_doc = sys.argv[1]
    env = sys.argv[2].lower()
else:
    if len(sys.argv) > 3:
        arg_problem = 'Too many args provided!'
    else:
        arg_problem = 'Not enough args provided!'

# logger setup - must have cms_integration_logging imported
# extras used in the json logger
extras = {"cms_environment": env, "script_version": script_version}
logger = cms_integration_logging.set_up_logging(sys.argv[0],env,script_version,log_level)

# start logging
logger.info(f'COMMENCING {script_name}.', extra=extras)
# bail out now if there was a problem with the number of args.
if arg_problem:
	logger.error(arg_problem)
	exit(1)

# log arg variables
logger.info(f'{env} provided as environment.', extra=extras)
logger.info(f'metadata provided: {metadata_doc}', extra=extras)

# project imports
import eng_vault_agent # need this for pretty much everything to get auth and ip addresses
import eng_vs_token # vs tools

# functions
def create_placeholder(vs, token):
    url = f'{vs}API/import/placeholder?container=1'
    headers = {
		'Content-Type': f'application/xml',
		'Authorization': f'token {token}'
	}
    try:
        response = requests.post(url, headers=headers, data=metadata_doc, verify=crt_file)
        response.raise_for_status()  # Raises an HTTPError if the response was unsuccessful
        return ET.fromstring(response.content).attrib['id']
    except HTTPError as http_err:
        raise HTTPError(f'HTTP error occurred: {http_err}')
    except Exception as err:
        raise RuntimeError(f'Other error occurred when posting: {err}')

def main():
    secret_path = f'v1/secret/{env}/vidispine/vantage'
    vs_secret_data = eng_vault_agent.get_secret(secret_path)
    username = vs_secret_data["username"]
    password = vs_secret_data["password"]
    vs = vs_secret_data["api_url"]
    seconds = 60
    basic_auth = eng_vs_token.get_basic_auth(username,password)
    vs_token_data = eng_vs_token.get_token_no_auto_refresh(vs,basic_auth,seconds)
    if not vs_token_data:
        logger.error("Didn't get token data from vidispine?")
        exit(2)
    placeholder_id = create_placeholder(vs, vs_token_data['token'])
    logger.info(f'placeholder id created: {placeholder_id}')
    sys.stdout.write(placeholder_id)
    return True

if __name__ == "__main__":
    try:
        main()
        exit(0)
    except Exception as e:
        logger.error(traceback.format_exc())
        exit(1)