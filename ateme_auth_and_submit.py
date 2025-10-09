#!/usr/bin/python3
# script version and log level
script_version = "240912.17"
log_level = "DEBUG" # DEBUG INFO WARN ERROR

'''
This script is meant to work with ateme_job_status.py

ARGUMENTS RECEIVED FROM VANTAGE:
1. Ateme authorization API endpoint
2. Ateme job creation API endpoint
3. Environment
4. Ateme job JSON object
'''

###CHANGE LOG###
'''
version 230918.09 - initial version: elemental_auth.py
version 240426.16 - added crt_file and moved logging
version 240827.17 - adapted for use with Ateme: ateme_auth.py
version 240908.14 - add job submission: ateme_auth_and_submit.py
version 240912.17 - remove cancel handling, keep token active
'''

#native imports
import json
import sys
import traceback
import time
import math
import requests

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

#project imports
import cms_integration_logging # need this for everything

# args to variables
script_name =  cms_integration_logging.get_script_name(sys.argv[0])
arg_problem = False
if len(sys.argv) == 5:
    ateme_auth_point = sys.argv[1]
    ateme_job_point = sys.argv[2]
    if sys.argv[3].lower() == 'uat':
        env = 'dev'
    else:
        env = sys.argv[3].lower()
    job = sys.argv[4]
else:
    if len(sys.argv) > 5:
        arg_problem = "Too many args provided!"
    else:
        arg_problem = "Not enough args provided!"

# logger setup - must have cms_integration_logging imported in project imports
# extras used in the json logger
extras = {"cms_environment": env, "script_version": script_version, "ateme_auth_point": ateme_auth_point, "ateme_job_point": ateme_job_point, "job_json": job}
logger = cms_integration_logging.set_up_logging(sys.argv[0],env,script_version,log_level)

# now we are ready for vault agent
import eng_vault_agent # need this for pretty much everything to get auth and ip addresses

# start logging
logger.info(f'COMMENCING {script_name}.', extra=extras)
# bail out now if there was a problem with the number of args or with the job json
if arg_problem:
    logger.error(arg_problem)
    exit(1)
try:
    json.loads(job)
except ValueError as e:
    logger.error(e)
    exit(1)

# log arg variables
logger.info(f'{ateme_auth_point} provided as ateme auth endpoint.', extra=extras)
logger.info(f'{ateme_job_point} provided as ateme job endpoint.', extra=extras)
logger.info(f'{env} provided as environment.', extra=extras)
logger.info(f'JSON job object provided: {job}', extra=extras)

# functions
def get_token(username,password,base_url):
    # ateme returns js object with four values: access token, refresh token, time limit, and token type (bearer)
    # build call
    headers = {
        'Accept': 'application/json',
        'Content-type': 'application/json',
        }
    data = {
            'username': username,
            'password': password
        }
    url_token = base_url + ateme_auth_point
    token_response = requests.post(url_token, headers=headers, json=data)
    if token_response.status_code == 200:
        logger.info(f'{env}: token request post status: {token_response.status_code}')
    else:
        logger.error(f'{env}: token request post status: {str(token_response.status_code)} content: {token_response.content}')
        exit(1)
    # put returns in python dict
    json_response = token_response.json()
    auth = {}
    # get current time and truncate ms
    t = time.time()
    t = math.trunc(t)
    # add time to now for length of auth
    s = json_response["expires_in"]
    auth_expires = t + s
    auth["X-Auth-User"] = username
    auth["X-Auth-Key"] = json_response["access_token"]
    auth["refresh_token"] = json_response["refresh_token"]
    auth["X-Auth-Expires"] = auth_expires
    return auth

def job_submit(base_url,token,job):
    headers = {
		'Content-type': 'application/json',
		'Authorization': f'Bearer {token}'
		}
    # send call to post job
    url_submit = base_url + ateme_job_point
    job_response = requests.post(url_submit, headers=headers, data=job)
    if job_response.status_code == 201:
        logger.info(f'{env}: job put status: {job_response.status_code}')
    else:
        logger.error(f'{env}: job put status: {str(job_response.status_code)} content: {job_response.content}')
        exit(1)
    # save job id for vantage
    json_job_response = job_response.json()
    return json_job_response['id']

def main():  
    secret_path = f'v1/secret/{env}/ateme/vantage'
    # get_secret function returns a dict
    secret_data = eng_vault_agent.get_secret(secret_path)
    # get dat token
    auth_data = get_token(secret_data["username"],secret_data["password"],secret_data["api_url"])
    # submit dat job
    job_id = job_submit(secret_data["api_url"],auth_data["X-Auth-Key"],job)
    auth_data["job-ID"] = job_id
    # write auth_data to stdout for vantage to consume
    sys.stdout.write(str(auth_data))
    logger.info(f'FINISHED.', extra=extras)
    return True

try:
    main()
    exit(0)
except Exception as e:
    logger.error(traceback.format_exc())
    exit(1)
