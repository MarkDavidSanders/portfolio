#!/usr/bin/python3
# script version and log level
script_version = "241007.17"
log_level = "DEBUG" # DEBUG INFO WARN ERROR

'''
ARGUMENTS RECEIVED FROM VANTAGE:
1. Template/Scheme ("Framerate Check")
2. SCC path
3. Task type
4. Priority
5. Environment

This script:
-Queries Vault as needed
-Gets auth token from BTC via API
-Submits item to BTC's Framerate Check test
-Pulls Frame Rate info from BTC Response
-Returns Frame Rate
'''
###CHANGE LOG###
'''
version 241007.17: Initial version
'''

#native imports
import json
import sys
import traceback
import time
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
if len(sys.argv) == 6:
	template = sys.argv[1]
	scc_path = sys.argv[2]
	task_type = sys.argv[3]
	priority = sys.argv[4]
	env = sys.argv[5].lower()
	if 'win32' in sys.platform:
		scc_linux = scc_path
	else:
		if scc_path.startswith('/mnt/Mezz'):
			scc_linux = scc_path
		elif scc_path.startswith("file://"):
			scc_linux = scc_path.replace("file://","")
		elif scc_path.startswith('M:\\'):
			# some asshole submitted a windows path on linux or mac
			scc_linux = scc_path.replace('M:', '/mnt/Mezz').replace('\\','/')
		else:
			arg_problem = "scc_path formatted incorrectly: " + scc_path
else:
    if len(sys.argv) > 6:
        arg_problem = "Too many args provided!"
    else:
        arg_problem = "Not enough args provided!"

# logger setup - must have cms_integration_logging imported in project imports
# extras used in the json logger
extras = {"cms_environment": env, "script_version": script_version, "template": template, "scc_path": scc_path, "task_type": task_type, "priority": priority}
logger = cms_integration_logging.set_up_logging(sys.argv[0],env,script_version,log_level)

# now we are ready for vault agent
import eng_vault_agent # need this for pretty much everything to get auth and ip addresses

# start logging
logger.info(f'COMMENCING {script_name}.', extra=extras)
# bail out now if there was a problem with the number of args
if arg_problem:
    logger.error(arg_problem)
    exit(1)

# args dict is for build_body
args = {'template': template, 'scc': scc_linux, 'task_type': task_type, 'priority': priority, 'instance': env}

# log arg variables
logger.info(f'{template} provided as btc test scheme.', extra=extras)
logger.info(f'{scc_path} provided as scc file path.', extra=extras)
logger.info(f'{task_type} provided as btc task type.', extra=extras)
logger.info(f'{priority} provided as btc priority.', extra=extras)
logger.info(f'{env} provided as environment.', extra=extras)

#functions
def get_bc_token(api_url, username, password):
	# gets a token from baton_caption
    headers = {
        'Accept': 'application/json',
        'Content-type': 'application/json',
        }
    data = {
        'username': username,
        'password': password
        }
    url = api_url + 'rest/auth-jwt'
    response = requests.request("POST", url, headers=headers, json=data, verify=False)
    results = json.loads(response.content)
    token = results['token']	
    return f'Bearer {token}'

def build_body(args):
	# build the body of the bc api call
	body = {'tasks': [{}]}
	tasks = body['tasks'][0]
	tasks['path'] = args['scc']
	tasks['priority'] = args['priority']
	# if args['tc'] != 'none':
	# 	tasks['start_time_offset'] = args['tc'] # don't think we need this but am not sure
	tasks['task_type'] = args['task_type']
	tasks['source_language'] = 'en'
	tasks['template_name'] = args['template']
	return body

def submit_job(api_url, body, token):
    headers = {
		'Content-type': 'application/json',
		'Authorization': token
		}
    url = api_url + "rest/tasks"
    response = requests.post(url, headers=headers, data=json.dumps(body), verify=False)
    response.raise_for_status()
    logger.warning(response)
    logger.warning(response.content)
    results = json.loads(response.content)
    try:
        task_id = results[0]['data']['id']
        subtask_id = results[0]['data']['subtasks'][0]['id']
    except KeyError:
        job_submit_error_status = results[0]['status']
        job_submit_error_detail = results[0]['detail'][0]['message']
        logger.error(f"Something went wrong with BTC job submission. Error status code: {job_submit_error_status}")
        logger.error(f"Error detail message: {job_submit_error_detail}")
        exit(1)
    return task_id, subtask_id

def status_check(api_url, task_id, subtask_id, token, request='status'):
    headers = {
		'Content-type': 'application/json',
		'Authorization': token
		}
    url = api_url + f'rest/tasks/{task_id}/{subtask_id}'
    response = requests.get(url, headers=headers, verify=False)
    results = json.loads(response.content)
    status = results[request]
    return status

def get_framerate_from_report(api_url, task_id, subtask_id, token):
    headers = {
        'Accept': 'application/json',
		'Authorization': token
        }
    params = {
        'includeErrors': True,
		'includeUtterances': False
        }
    url = api_url + f'rest/tasks/report/{task_id}/{subtask_id}'
    response = requests.get(url, headers=headers, params=params, verify=False)
    report = json.loads(response.content)
    framerate_message = report['ccTrackReports'][0]['trackTypes'][0]['ccReports'][0]['sections'][2]['summary']['framerate']['result']
    return framerate_message

def main():
    secret_path = f'v1/secret/{env}/bc/admin'
    secret_data = eng_vault_agent.get_secret(secret_path)
    api_url = secret_data["api_url"]
    username = secret_data["username"]
    password = secret_data["password"]
    # get dat token
    token = get_bc_token(api_url, username, password)
    # build dat job body
    body = build_body(args)
    logger.warning(body)
    # do job
    task_id, subtask_id = submit_job(api_url, body, token)
    time.sleep(5)
    logger.warning(task_id)
    # check status, wait a minute if not complete
    complete = False
    while not complete:
        status = status_check(api_url, task_id, subtask_id, token)
        if status == 'ABO':
            complete = True
            status_description = status_check(api_url, task_id, subtask_id, token, request='status_description')
            logger.warning('Abort Status Reached')
            logger.warning(status_description)
            exit(1)
        elif status == 'FIN':
            complete = True
        else:
            time.sleep(60)
    # when complete, get report
    framerate_message = get_framerate_from_report(api_url, task_id, subtask_id, token)
    # lose the text and the period at the end
    framerate = framerate_message[:-1].replace(" Caption timecodes have a framerate of ", "")
        # write auth_data to stdout for vantage to consume
    sys.stdout.write(str(framerate))
    logger.info(f'FINISHED.', extra=extras)
    return True

if __name__ == "__main__":
    try:
        main()
        exit(0)
    except Exception as e:
        logger.error(traceback.format_exc())
        exit(1)
