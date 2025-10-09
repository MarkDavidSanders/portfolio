#!/usr/bin/python3
# script version and log level
script_version = "240711.18"
log_level = "DEBUG" # DEBUG INFO WARN ERROR

# ARGS - this script receives the following args:

## item_id
## mixdown_path (WINDOWS PATH!)
## template
## scc_path (WINDOWS PATH!)
## start_tc_offset
## task_type
## priority
## env
## sidecar_caption_id
## correction_path

'''
test
needs the path to the downmix audio and the scc
using dev VX-10265 to test, get the paths

http://dev-vs:8080/API/item/VX-10265?content=shape&tag=downmix_analysis_audio
file:///mnt/Mezz/ADMIN/Extracted_Assets_DEV/Extracted_Audio_DEV/VX-10265/VX-10265_downmix.mov
M:\ADMIN\Extracted_Assets_DEV\Extracted_Audio_DEV\VX-10265\VX-10265_downmix.mov

http://dev-vs:8080/API/item/VX-10265?content=shape&tag=extracted_scc
file:///mnt/Mezz/ADMIN/Extracted_Assets_DEV/Extracted_CC_DEV/VX-10265/VX-10265.1.scc
M:\ADMIN\Extracted_Assets_DEV\Extracted_CC_DEV\VX-10265\VX-10265.1.scc

convert paths to windows

python3 C:\cms_integrations\scripts\baton_caption\baton_caption.py "VX-10265" "M:\ADMIN\Extracted_Assets_DEV\Extracted_Audio_DEV\VX-10265\VX-10265_downmix.mov" "iND Kitchen Sink - Mezz" "M:\ADMIN\Extracted_Assets_DEV\Extracted_CC_DEV\VX-10265\VX-10265.1.scc" "00:00:00:00" "qc" "3" "dev"

'''

#native imports
import requests
requests.packages.urllib3.disable_warnings()
from requests.exceptions import HTTPError
import json
import sys

from time import sleep
import re
import traceback

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
if len(sys.argv) == 11:
	item_id = sys.argv[1]
	mixdown_path = sys.argv[2]
	template = sys.argv[3]
	scc_path = sys.argv[4]
	start_tc_offset = sys.argv[5]
	task_type = sys.argv[6]
	priority = sys.argv[7]
	env = sys.argv[8].lower()
	sidecar_caption_id = sys.argv[9]
	correction_path = sys.argv[10]
	if 'win32' in sys.platform:
		scc_linux = scc_path.replace('M:', '/mnt/Mezz').replace('\\','/')
		mixdown_linux = mixdown_path.replace('M:', '/mnt/Mezz').replace('\\','/')
		correction_linux = correction_path.replace('M:', '/mnt/Mezz').replace('\\','/')
	else:
		if scc_path.startswith("file://"):
			scc_linux = scc_path.replace("file://","")
		elif scc_path.startswith('/mnt/Mezz'):
			scc_linux = scc_path
		elif scc_path.startswith('M:\\'):
			# some asshole submitted a widowns path on linux or mac
			scc_linux = scc_path.replace('M:', '/mnt/Mezz').replace('\\','/')
		else:
			arg_problem = "scc_path formatted incorrectly: " + scc_path
		if mixdown_path.startswith("file://"):
			mixdown_linux = mixdown_path.replace("file://","")
		elif mixdown_path.startswith('/mnt/Mezz'):
			mixdown_linux = mixdown_path
		elif mixdown_path.startswith("M:\\"):
			# some asshole submitted a widowns path on linux or mac
			mixdown_linux = mixdown_path.replace('M:', '/mnt/Mezz').replace('\\','/')
		else:
			arg_problem = "mixdown_path formatted incorrectly: " + mixdown_path
		if correction_path.startswith("file://"):
			correction_linux = correction_path.replace("file://","")
		elif correction_path.startswith('/mnt/Mezz'):
			correction_linux = correction_path
		elif correction_path.startswith("M:\\"):
			# some asshole submitted a widowns path on linux or mac
			correction_linux = correction_path.replace('M:', '/mnt/Mezz').replace('\\','/')
		else:
			arg_problem = "correction_path formatted incorrectly: " + correction_path

else:
	if len(sys.argv) > 11:
		arg_problem = "Too many args provided!"
	else:
		arg_problem = "Not enough args provided!"

# logger setup - must have cms_integration_logging imported in project imports
# extras used in the json logger
extras = {"cms_environment": env, "script_version": script_version}
logger = cms_integration_logging.set_up_logging(sys.argv[0],env,script_version,log_level)


# bail out now if there was a problem with the number of args.
if arg_problem:
	logger.error(arg_problem)
	exit(1)
else:
	# start logging
	logger.info(f'COMMENCING {script_name}.', extra=extras)

# args is used to build the body of the baton caption api call
args = {'item_id': item_id, 'mixdown': mixdown_path,
	'template': template, 'scc': scc_path,
	'tc': start_tc_offset, 'task': task_type,
	'priority': priority, 'instance': env,
	'scc_linux': scc_linux, 'mixdown_linux': mixdown_linux}

# log arg variables
logger.info(f'{env} provided as environment.', extra=extras)
logger.info(f'{item_id} provided as the item.', extra=extras)
logger.info(f'{mixdown_path} provided as the mixdown_path.', extra=extras)
logger.info(f'{template} provided as the template.', extra=extras)
logger.info(f'{scc_path} provided as the scc_path.', extra=extras)
logger.info(f'{start_tc_offset} provided as the start_tc_offset.', extra=extras)
logger.info(f'{task_type} provided as the task_type.', extra=extras)
logger.info(f'{priority} provided as the priority.', extra=extras)
logger.info(f'{sidecar_caption_id} provided as the sidecar_caption_id.', extra=extras)


#project imports
import eng_vault_agent # need this for pretty much everything to get auth and ip addresses
import eng_vs_token # vs tools


# custom functions:

def get_bc_token(api_url,username,password):
	# gets a token from baton_caption
	headers = {'content-type': 'application/json'}
	data = {'username': username, 'password': password}
	# url https://dev-bc.vcnyc.indemand.net:1412/
	url = api_url + 'rest/auth-jwt'
	response = requests.request("POST", url, headers=headers, data=json.dumps(data), verify=False)
	results = json.loads(response.content)
	token = results['token']
	
	return f'Bearer {token}'

def build_body(args):
	# build the body of the bc api call
	body = {'tasks': [{}]}
	tasks = body['tasks'][0]
	tasks['path'] = args['mixdown_linux']
	tasks['priority'] = args['priority']
	if args['tc'] != 'none':
		tasks['start_time_offset'] = args['tc']
	tasks['task_type'] = args['task']
	tasks['source_language'] = 'en'
	tasks['template_name'] = args['template']
	tasks['text_file_paths'] = [args['scc_linux']]

	return body


def submit_job(api_url, body, token):
	headers = {'content-type': 'application/json',
			   'authorization': token}
	url = api_url + "rest/tasks"
	response = requests.request("POST", url, headers=headers, data=json.dumps(body), verify=False)
	response.raise_for_status()
	logger.warning(response)
	logger.warning(response.content)
	results = json.loads(response.content)
	task_id = results[0]['data']['id']
	subtask_id = results[0]['data']['subtasks'][0]['id']
	
	return task_id, subtask_id


def status_check(api_url, task_id, subtask_id, token, request='status'):
	headers = {'authorization': token,
				'content-type': 'application/json'}
	url = api_url + f'rest/tasks/{task_id}/{subtask_id}'
	response = requests.request("GET", url, headers=headers, verify=False)
	results = json.loads(response.content)
	status = results[request]

	return status

def retrieve_task_report(api_url, task_id, subtask_id, token):
	headers = {'authorization': token,
			   'accept': 'application/json'}
	params = {'includeErrors': False,
				'includeUtterances': False}
	url = api_url + f'rest/tasks/report/{task_id}/{subtask_id}'
	response = requests.request("GET", url, headers=headers, params=params, verify=False)
	report = json.loads(response.content)

	return report
  

def check_for_failure(report):
	'''sections = report['ccTrackReports'][0]['trackTypes'][0]['ccReports'][0]['sections']
	if sections[2]['name'] == 'Common':
		failure_type = list(sections[2]['summary'].keys())[0]
		failure_result = sections[2]['summary'][failure_type]['result']
		return (True, failure_result)
	else:
		return (False, '')'''
		
	sections = report['ccTrackReports'][0]['trackTypes'][0]['ccReports'][0]['sections']
	for index, section in enumerate(sections):
		if section['name'] == 'Common':
			failure_type = list(sections[index]['summary'].keys())[0]
			failure_result = sections[index]['summary'][failure_type]['result']
			return (True, failure_result)
	return (False, '')

def extract_success_values(report):
	results = {}
	'''summaries = report['ccTrackReports'][0]['trackTypes'][0]['ccReports'][0]['sections'][0]['summary']
	for summary in summaries:
			results[summary] = {}
			results[summary]['restriction'] = summaries[summary]['restriction']
			results[summary]['status'] = summaries[summary]['status'].capitalize()
			results[summary]['result'] = summaries[summary]['result']
	return results'''

	sections = report['ccTrackReports'][0]['trackTypes'][0]['ccReports'][0]['sections']
	for section in sections:
		summaries = section['summary']
		for summary in summaries:
			results[summary] = {}
			results[summary]['restriction'] = summaries[summary]['restriction']
			results[summary]['status'] = summaries[summary]['status'].capitalize()
			results[summary]['result'] = summaries[summary]['result']
	
	return results

def make_group_metadata_doc(group,field,value):
	metadata = {
		"timespan": [
			{
				"start": "-INF",
				"end": "+INF",
				"group": [
					{
						"name": group,
						"field": [
							{
								"name": field,
								"value": [
									{
										"value": value
									}
								]
							}
						]
					}
				]
			}
		]
	}

	return metadata

def update_metadata(vs_token_data, results, item_id):
	# update the metadata in vs for each field and return a list of dicts with the results
	# [{'sidecar_caption_analysis_arruracy_status': 'whatever'},etc]
	field_pairings = {'accuracy': 'incorrect',
					  'completeness': 'missing',
					  'display_duration': 'duration',
					  'caption_shift': 'shift',
					  'caption_drift': 'drift',
					  'character_count': 'line_length',
					  'row_count': 'line_count',
					  'reading_speed': 'reading_rate',
					  'language': 'language'}
	results_list = []
	for pairing in field_pairings:
		result_dict = {}
		group = 'sidecar_caption_analysis'
		field = f'{group}_{field_pairings[pairing]}'
		criteria_update = make_group_metadata_doc(group,field + '_criteria',results[pairing]['restriction'])
		result_dict[field + '_criteria'] = results[pairing]['restriction']
		logger.info(criteria_update)
		status_update = make_group_metadata_doc(group,field + '_status',results[pairing]['status'])
		result_dict[field + '_status'] = results[pairing]['status']
		logger.info(status_update)
		result_update = make_group_metadata_doc(group,field + '_summary',results[pairing]['result'])
		result_dict[field + '_summary'] = results[pairing]['result']
		logger.info(result_update)
		u = eng_vs_token.put_item_metadata(vs_token_data,item_id,criteria_update)
		logger.debug(str(u))
		u = eng_vs_token.put_item_metadata(vs_token_data,item_id,status_update)
		logger.debug(str(u))
		u = eng_vs_token.put_item_metadata(vs_token_data,item_id,result_update)
		logger.debug(str(u))
		results_list.append(result_dict)
	return results_list





def update_metadata_fail(vs_token_data, result, item_id):
	fields = ['shift', 'drift', 'incorrect', 'missing', 'duration',
			  'line_length', 'line_count', 'reading_rate']
	group = 'sidecar_caption_analysis'
	for field in fields:
		f = f'{group}_{field}'
		status_update = make_group_metadata_doc(group,f + '_status','Fail')
		summary_update = make_group_metadata_doc(group,f + '_summary',result)
		u = eng_vs_token.put_item_metadata(vs_token_data,item_id,status_update)
		logger.warning(str(u))
		u = eng_vs_token.put_item_metadata(vs_token_data,item_id,summary_update)
		logger.warning(str(u))


def download_corrected_captions(correction_path, correction_linux, item_id, api_url, task_id, subtask_id, token):
	if 'win32' in sys.platform:
		path = '\\'.join(correction_path.split('\\')[:-1])
	else:
		path = '/'.join(correction_linux.split('/')[:-1])
	filename = f'{item_id}_aligned.scc'
	corrected_scc_path = '\\'.join([path, filename])
	headers = {'authorization': token}
	url = api_url + f'rest/tasks/export_captions/{task_id}/{subtask_id}?format_captions=SCC'
	response = requests.request("GET", url, headers=headers, verify=False)
	results = response.content
	results = results.decode("utf-8")
	with open(corrected_scc_path, 'w') as f:
		f.write(results)
		f.close()

def get_vs_token():
	# get_vault_secret_data - function returns a dict
	# vs secret
	secret_path = f'v1/secret/{env}/vidispine/vantage'
	vs_secret_data = eng_vault_agent.get_secret(secret_path)
	username = vs_secret_data["username"]
	password = vs_secret_data["password"]
	vs = vs_secret_data["api_url"]
	vs_auth = eng_vs_token.get_basic_auth(username,password)
	ttl = 20
	token_data = eng_vs_token.get_auto_refresh_token(vs,vs_auth,ttl)
	if token_data:
		return token_data
	else:
		logger.error("Could not get VS token!")
		exit(1)

def main():
	# put the sidecar item id to the item metadata
	metadata = make_group_metadata_doc("sidecar_caption_analysis","sidecar_caption_analysis_item_id",sidecar_caption_id)
	vs_token_data = get_vs_token()
	eng_vs_token.put_item_metadata(vs_token_data,item_id,metadata)
	
	# bc secret
	secret_path = f'v1/secret/{env}/bc/admin'
	secret_data = eng_vault_agent.get_secret(secret_path)
	api_url = secret_data["api_url"]
	username = secret_data["username"]
	password = secret_data["password"]
	
	# get bc token
	bc_token = get_bc_token(api_url,username,password)
	body = build_body(args)
	logger.warning(body)
	
	# submit job
	job, subtask_id = submit_job(api_url, body, bc_token)
	sleep(5)
	logger.warning(job)

	# check job status
	complete = False
	abort = False
	while not complete:
		status = status_check(api_url, job, subtask_id, bc_token)
		if status == 'ABO':
			status_description = status_check(api_url, job, subtask_id, bc_token, request='status_description')
			logger.warning('Abort Status Reached')
			logger.warning(status_description)
			if status_description != 'Captions not found':
				logger.error('Captions not found in sidecar.')
				exit(404)
			else:
				exit(1)
		elif status == 'FIN':
			complete = True
		else:
			sleep(60)

	# we have a completed job, get the report
	report = retrieve_task_report(api_url, job, subtask_id, bc_token)
		
	completed_values = extract_success_values(report)
	
	vs_token_data = get_vs_token()

	results_list = update_metadata(vs_token_data,completed_values,item_id)

	# check for a corrected file
	correction = report['ccTrackReports'][0]['trackTypes'][0]['ccReports'][0]['correction']
	
	if correction:
		logger.debug(correction)
		logger.warning(f'Downloading Corrected Captions for {item_id}')
		download_corrected_captions(correction_path, correction_linux, sidecar_caption_id, api_url, job, subtask_id, bc_token)
		sys.stdout.write(json.dumps(results_list))
		return True
	else:
		sys.stdout.write(json.dumps(results_list))
		return True


if __name__ == "__main__":
	metadata_skip_templates = ['iND Correction']
	caption_skip_templates = []
	try:
		main()
		exit(0)
	except Exception as e:
		logger.error(traceback.format_exc())
		exit(1)
