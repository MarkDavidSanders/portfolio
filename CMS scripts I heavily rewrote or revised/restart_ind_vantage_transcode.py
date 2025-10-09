#!/usr/bin/python3
# script version and log level
script_version = "250303.12"
log_level = "DEBUG" # DEBUG INFO WARN ERROR

'''
ARGUMENTS RECEIVED FROM CLI SUBMISSION:
1. ENVIRONMENT
2. JOB_IDS

WHAT THIS SCRIPT DOES:
-Convertes JOB_IDS comma delimited string to a list of job ids
-Gets VS secrets from Vault
-Constructs and sends a job re-run POST call for each job id
-Gets new job id
-Inserts old job id into new job as job metadata as original_job_id
'''
###CHANGE LOG###
'''
version 250303.12 - initial version
'''

#native imports
import sys
import traceback
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

# import logging module
import cms_integration_logging # need this for everything

# args to variables:
script_name =  cms_integration_logging.get_script_name(sys.argv[0])
arg_problem = False
if len(sys.argv) == 3:
	env = sys.argv[1].lower()
	job_ids_input = sys.argv[2]
	job_ids = job_ids_input.split(',')
else:
	if len(sys.argv) > 3:
		arg_problem = "Too many args provided!"
	else:
		arg_problem = "Not enough args provided!"
            
	


# bail out now if there was a problem with the number of args.
if arg_problem:
	# logger setup - must have cms_integration_logging imported in project imports
	logger = cms_integration_logging.set_up_logging(sys.argv[0],"unknown",script_version,log_level)
	logger.error(arg_problem)
	exit(1)
else:
	# logger setup - must have cms_integration_logging imported in project imports
	logger = cms_integration_logging.set_up_logging(sys.argv[0],env,script_version,log_level)
	# extras used in the json logger
	extras = {"cms_environment": env, "script_version": script_version}
	# start logging
	logger.info(f'COMMENCING {script_name}.', extra=extras)

# log arg variables
logger.info(f'{env} provided as environment.', extra=extras)
logger.info(f'{job_ids_input} provided as the job id(s).', extra=extras)


#project imports
import eng_vault_agent # need this for pretty much everything to get auth and ip addresses
import eng_vs_token # vs tools

# custom functions

# function to check if job id being re-submitted already has an original_job_id embedded
def check_for_original_job_id(job_id, vs, vs_auth, token):
	# check for original_job_id in job data
	# return false if not found, else return original_job_id
	url = f'{vs}API/job/{job_id}?metadata=true'
	headers = {
		'Authorization': f'token {token}',
		'Accept': 'application/json'
	}
	response = requests.get(url, headers=headers, verify=crt_file)
	if response.status_code >= 300:
		logger.error(f'Could not get job {job_id}. Status code {response.status_code}')
		return False
	else:
		job_doc = response.json()
		job_data =  job_doc['data']
		for data in job_data:
			if data['key'] == 'original_job_id':
				return data['value']
		return False
	
def main():
	# get_vault_secret_data function returns a dict
	secret_path = f'v1/secret/{env}/vidispine/vantage'
	vs_secret_data = eng_vault_agent.get_secret(secret_path)
	username = vs_secret_data["username"]
	password = vs_secret_data["password"]
	vs = vs_secret_data["api_url"]
	vs_auth = eng_vs_token.get_basic_auth(username,password)
	ttl = 10
	token_data = eng_vs_token.get_token_no_auto_refresh(vs, vs_auth, ttl)
	if token_data:
		token = token_data["token"]
		for job_id in job_ids:
			post_url = f'{vs}API/job/{job_id}/re-run'
			headers = {
				'Authorization': f'token {token}',
				'Accept': 'application/json'
			}
			response = requests.post(post_url, headers=headers, verify=crt_file)
			
			if response.status_code >= 300:
				logger.error(f'Job {job_id} not re-ran. Status code {response.status_code}')
				exit(1)
			else:
				job_doc = response.json()
				new_job_id = job_doc["jobId"]
				logger.info(f'Job {job_id} successfully re-ran. New job id {new_job_id}.')
				# check if old job id already had original_job_id metadata
				old_original_job_id = check_for_original_job_id(job_id, vs, vs_auth, token)
				if old_original_job_id:
					# insert old_original_job_id into new job as original_job_id
					eng_vs_token.update_job_metadata(token_data,new_job_id,'original_job_id',old_original_job_id)
				else:
					# insert original_job_id into new job
					eng_vs_token.update_job_metadata(token_data,new_job_id,'original_job_id',job_id)
		return True
	else:
		logger.error("Didn't get token data from vidispine?")
		exit(2)

try:
	main()
	exit(0)
except Exception as e:
	logger.error(traceback.format_exc())
	exit(1)
