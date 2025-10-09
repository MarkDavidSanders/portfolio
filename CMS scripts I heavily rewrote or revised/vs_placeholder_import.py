#!/usr/bin/python3
# script version and log level
script_version = "250203.10"
log_level = "INFO" # DEBUG INFO WARN ERROR
'''
ARGUMENTS RECEIVED FROM VANTAGE:
1. VS Placeholder ID
2. VS File ID
3. Environment

WHAT THIS SCRIPT DOES:
-Gets Vault secrets
-Constructs and sends POST call to import the file into the placeholder
-Returns job ID
'''

# native imports
import sys, requests, traceback
from requests.exceptions import HTTPError

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
if len(sys.argv) == 4:
    if sys.argv[1].startswith('VX-') and sys.argv[2].startswith('VX-'):
        placeholder_id = sys.argv[1]
        file_id = sys.argv[2]
    else:
        arg_problem = 'Bad arguments provided. ID values must start with "VX-".'
    env = sys.argv[3].lower()
else:
    if len(sys.argv) > 4:
        arg_problem = 'Too many arguments!'
    else:
        arg_problem = 'Not enough arguments!'

# logger setup - must have cms_integration_logging imported
# extras used in the json logger
extras = {"cms_environment": env, "script_version": script_version}
logger = cms_integration_logging.set_up_logging(sys.argv[0],env,script_version,log_level)

# start logging
logger.info(f'COMMENCING {script_name}.', extra=extras)

# log arg variables
logger.info(f'{env} provided as environment.', extra=extras)
logger.info(f'{placeholder_id} provided as placeholder id.', extra=extras)
logger.info(f'{file_id} provided as file id.', extra=extras)

# project imports
import eng_vault_agent # need this for pretty much everything to get auth and ip addresses
import eng_vs_token # vs tools

# let's do it
def import_placeholder(vs, token):
    url = f'{vs}API/import/placeholder/{placeholder_id}/container?fileId={file_id}&priority=HIGH'
    headers = {'Authorization': f'token {token}'}
    try:
        response = requests.post(url, headers=headers, verify=crt_file)
        response.raise_for_status()  # Raises an HTTPError if the response was unsuccessful
        job_doc = eng_vs_token.xml_prep(response)
        return job_doc.find('jobId').text
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
    job_id = import_placeholder(vs, vs_token_data['token'])
    logger.info(f'placeholder imported. job id created: {job_id}')
    sys.stdout.write(job_id)
    return True

if __name__ == "__main__":
    try:
        main()
        exit(0)
    except Exception as e:
        logger.error(traceback.format_exc())
        exit(1)