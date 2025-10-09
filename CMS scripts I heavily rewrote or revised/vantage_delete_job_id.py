#!/usr/bin/python3
# script version and log level
script_version = "250203.09"
log_level = "INFO" # DEBUG INFO WARN ERROR
'''
ARGUMENTS RECEIVED FROM VANTAGE:
1. Job ID
2. Environment

WHAT THIS SCRIPT DOES:
Deletes the job
'''

# native imports
import sys, requests

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
job_id = sys.argv[1]
try:
    env = sys.argv[2].lower()
except:
    env = 'prod'

# logger setup - must have cms_integration_logging imported
# extras used in the json logger
extras = {"cms_environment": env, "script_version": script_version}
logger = cms_integration_logging.set_up_logging(sys.argv[0],env,script_version,log_level)

# start logging
logger.info(f'COMMENCING {script_name}.', extra=extras)

# log arg variables
logger.info(f'{env} provided as environment.', extra=extras)
logger.info(f'{job_id} provided as the vantage job id.', extra=extras)

# project imports
import eng_vault_agent # need this for pretty much everything to get auth and ip addresses

# here we go
vantage_path = f'v1/secret/{env}/vantage/vantage'
vantage = eng_vault_agent.get_secret(vantage_path)['api_url']

requests.delete(f'{vantage}Rest/Jobs/{job_id}/Remove', verify=False)
logger.info(f'Delete call sent for job ID {job_id}.', extra=extras)
exit(0)