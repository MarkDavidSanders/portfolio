#!/usr/bin/python3
# script version and log level
script_version = "240912.13"
log_level = "DEBUG" # DEBUG INFO WARN ERROR

'''
ARGUMENTS RECEIVED FROM VANTAGE:
1. Ateme refresh token API endpoint
2. Ateme jobs API endpoint (status point)
3. Ateme cancel token API endpoint
4. Ateme auth token
4. Ateme refresh token
5. Ateme job ID
6. Environment

WHAT THIS SCRIPT DOES:
1. Gets Ateme URL from Vault
2. Call Ateme to refresh token, return new tokens
3. If refresh call returns 400 response, call for a brand new token
4. Use job ID and new auth token to make a status call to Ateme
5. If job status is neither "pending" nor "running", cancel token
6. Return job status for Vantage to consume
'''

###CHANGE LOG###
'''
version 240912.13 - initial version
'''

#native imports
import sys
import traceback
import requests
import time
import math

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
if len(sys.argv) == 8:
    ateme_refresh_point = sys.argv[1]
    ateme_status_point = sys.argv[2]
    ateme_cancel_point = sys.argv[3]
    ateme_auth_token = sys.argv[4]
    ateme_refresh_token = sys.argv[5]
    job_id = sys.argv[6]
    if sys.argv[7].lower() == 'uat':
        env = 'dev'
    else:
        env = sys.argv[7].lower()
else:
    if len(sys.argv) > 8:
        arg_problem = "Too many args provided!"
    else:
        arg_problem = "Not enough args provided!"

# logger setup - must have cms_integration_logging imported in project imports
# extras used in the json logger
extras = {"cms_environment": env, "script_version": script_version, "ateme_refresh_point": ateme_refresh_point, "ateme_status_point": ateme_status_point, "ateme_cancel_point": ateme_cancel_point, "ateme_auth_token": ateme_auth_token, "ateme_refresh_token": ateme_refresh_token, "job_id": job_id}
logger = cms_integration_logging.set_up_logging(sys.argv[0],env,script_version,log_level)

# now we are ready for vault agent
import eng_vault_agent # need this for pretty much everything to get auth and ip addresses

# start logging
logger.info(f'COMMENCING {script_name}.', extra=extras)
# bail out now if there was a problem with the number of args
if arg_problem:
    logger.error(arg_problem)
    exit(1)

# log arg variables
logger.info(f'{ateme_refresh_point} provided as ateme token refresh endpoint.', extra=extras)
logger.info(f'{ateme_cancel_point} provided as ateme auth cancellation endpoint.', extra=extras)
logger.info(f'{ateme_status_point} provided as ateme job status endpoint.', extra=extras)
logger.info(f'{ateme_auth_token} provided as ateme auth token.', extra=extras)
logger.info(f'{ateme_refresh_token} provided as ateme refresh token.', extra=extras)
logger.info(f'{job_id} provided as ateme job ID.', extra=extras)
logger.info(f'{env} provided as environment.', extra=extras)

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
    url_token = base_url + 'users/token'
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

def refresh(base_url,auth_token,refresh_token):
    headers = {
        'Content-type': 'application/json',
        'Authorization': f'Bearer {auth_token}'
        }
    data = {
        'refresh_token': f'{refresh_token}'
        }
    url_refresh = base_url + ateme_refresh_point
    token_response = requests.post(url_refresh, headers=headers, json=data)
    if token_response.status_code == 200:
        logger.info(f'{env}: token request post status: {token_response.status_code}')
    else:
        logger.error(f'{env}: token request post status: {str(token_response.status_code)} content: {token_response.content}')
        if token_response.status_code == 400:
            return 400
        else:
            exit(1)
    json_response = token_response.json()
    return json_response["access_token"]

def get_status(base_url,new_auth_token,job_id):
    headers = {
        'Content-type': 'application/json',
        'Authorization': f'Bearer {new_auth_token}'
        }
    url_status = base_url + ateme_status_point + '/' + job_id + '/state'
    status_response = requests.get(url_status, headers=headers)
    if status_response.status_code != 200:
        logger.error(f'{env}: get status: {str(status_response.status_code)} content: {status_response.content}')
        exit(1)
    else:
        logger.info(f'{env}: get status: {status_response.status_code}')
        return status_response.text

def cancel_token(base_url,token):
    headers = {
        'Content-type': 'application/json',
        'Authorization': f'Bearer {token}'
        }
    url_cancel = base_url + ateme_cancel_point
    cancel_response = requests.delete(url_cancel, headers=headers)
    if cancel_response.status_code != 200:
        logger.error(f'{env}: token delete status: {str(cancel_response.status_code)} content: {cancel_response.content}')
        exit(1)
    else:
        logger.info(f'{env}: token delete status: {cancel_response.status_code}')
        return True

def main():  
    secret_path = f'v1/secret/{env}/ateme/vantage'
    # get_secret returns a dict
    secret_data = eng_vault_agent.get_secret(secret_path)
    # refresh dat token
    new_auth_token = refresh(secret_data["api_url"],ateme_auth_token,ateme_refresh_token)
    if new_auth_token == 400:
        new_auth_token = get_token(secret_data["username"],secret_data["password"],secret_data["api_url"])["X-Auth-Key"]
    # get dat status
    job_status = get_status(secret_data["api_url"],new_auth_token,job_id)
    logger.info(f'Job status: {job_status}')
    # if job has stopped, cancel dat token
    if job_status =='"complete"':
        cancel_token(secret_data["api_url"],new_auth_token)
    # write job_status to stdout for vantage to consume
    sys.stdout.write(str(job_status))
    logger.info(f'FINISHED.', extra=extras)
    return True

try:
    main()
    exit(0)
except Exception as e:
    logger.error(traceback.format_exc())
    exit(1)
