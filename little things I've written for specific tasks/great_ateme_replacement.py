#!/usr/bin/python3
import requests
import xml.etree.ElementTree as ET
import sys
import logging
import os
import getpass
import csv
import time

'''
THIS SCRIPT REQUIRES:
1. Old item ID
2. Parent ID
3. Caption ID (optional)
4. Transcode profile

All four requirements are passed in via CSV file

For each old item ID:
- Delete original_shape_mi_original_shape_mi_md5_hash value
- Delete ateme_vs_jobid
- Search for external-id
- If found, store external-id value in a variable and delete it from metadata
-- If external-id not found, get item's URI value
-- Get the name of the folder immediately following "/ateme_transcodes/" and use that as external-id
-- Conduct a search for items containing the external-id
-- Delete the item found (ask permission first?)
- Return old item to placeholder
- Pull language value(s) from external-id
- Build and send new transcode call
- Put new ateme_vs_jobid into metadata


https://prod-vs.indemand.com:8443/API/job?type=ind_ateme_transcode&jobmetadata=itemId={parentID}&jobmetadata=transcode_profile={transcodeProfile}&jobmetadata=track_1_lang={track1lang}&jobmetadata=track_2_lang={track2lang}jobmetadata=placeholder_item_id=VX-{placeholderID}
'''

def get_env():
	# this function asks the user to enter the environment name
	print()
	env = input('Enter the environment we are restarting failed proxies on: (dev, uat, prod)\n')
	env = env.lower()
	if env == 'dev' or env == 'uat' or env == 'prod':
		print(f'\nThank you kind sir/madam for your most generous and enlightening instructions. We will be working on: {env}.\n')
		return env
	else:
		print('\noops try again. must be dev, uat, or prod\n')
		get_env()
		
# check if an environment arguement was passed to the script, if not ask for input

if len(sys.argv) == 1:
	# sys.argv[0] is always the script's path so that would count as the one argument
	# so we know the argument was not passed - ask for user input
	environment = get_env()
else:
	# more than one argument was passed so lets see if the format is good
	environment = sys.argv[1]
	environment = environment.lower()
	if environment not in ["prod","dev","uat"]:
		# format of the enviroment argument wasn't good, ask for user input
		print()
		print('Argument passed to script was not an environment name: dev, uat, or prod')
		print(f'Argument passed: {sys.argv[1]}')
		print()
		environment = get_env()

script_path = sys.argv[0]
# get the script file name from the path
script_file_name = script_path[script_path.rfind('/')+1:]
script_file_name_no_extention = script_file_name[0:script_file_name.rfind('.')]
log_file = script_path.replace(script_file_name,script_file_name_no_extention+'.log')
proxy_config_file = script_path.replace(script_file_name,'proxy_config.xml')

if not os.path.exists(log_file):
	# use with to create the file via open() and it will close automatically
	with open(log_file, 'w'): pass

logging.basicConfig(filename=log_file, level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')

# functions

def xml_prep(res):
	# prepare a VS xml for parsing with ET
	res = res.content
	res = res.decode(encoding='utf-8', errors='strict')
	# because I hate dealing with the namespace in ET
	res = res.replace(' xmlns=\"http://xml.vidispine.com/schema/vidispine\"', "")
	res = res.encode(encoding='utf-8', errors='strict')
	res = ET.fromstring(res)
	return res

def get_variables_from_config(environment,proxy_config):
	env = proxy_config.findall('environment')
	for e in env:
		if e.find('short_name').text == environment:
			vs = e.find('vidispine/ip_address').text
			vs_auth = e.find('vidispine/auth').text
			break
	return vs,vs_auth

def delete_md5_hash(vs,vs_auth,old_item_id):
	put_url = f'{vs}API/item/{old_item_id}/metadata'
	body = '''
	<MetadataDocument xmlns="http://xml.vidispine.com/schema/vidispine">
        <timespan end="+INF" start="-INF">
            <group>
                <name>original_shape_mi</name>
                <field>
                    <name>original_shape_mi_original_shape_mi_md5_hash</name>
                    <value></value>
                </field>
            </group>
        </timespan>
    </MetadataDocument>
    '''
	headers = {
		'Accept': 'application/xml',
		'Authorization': vs_auth
    }
	put_response = requests.put(put_url, headers=headers, data=body)
	if put_response.status_code != 200:
		print(f'Failed to delete md5 hash for item {old_item_id}! Aborting.')
		exit(1)
	else:
		print(f'Successfully deleted md5 hash for item {old_item_id}.')
		return True

def delete_ateme_job_id(vs,vs_auth,old_item_id):
	put_url = f'{vs}API/item/{old_item_id}/metadata'
	body = '''
	<MetadataDocument xmlns="http://xml.vidispine.com/schema/vidispine">
        <timespan end="+INF" start="-INF">
            <group>
                <name>ateme</name>
                <field>
                    <name>ateme_vs_jobid</name>
                    <value></value>
                </field>
            </group>
        </timespan>
    </MetadataDocument>
    '''
	headers = {
		'Accept': 'application/xml',
		'Authorization': vs_auth
    }
	put_response = requests.put(put_url, headers=headers, data=body)
	if put_response.status_code != 200:
		print(f'Failed to delete old Ateme job ID for item {old_item_id}! Aborting.')
		exit(1)
	else:
		print(f'Successfully deleted old Ateme job ID for item {old_item_id}.')
		return True

def put_new_ateme_job_id(vs,vs_auth,old_item_id,job_id):
	put_url = f'{vs}API/item/{old_item_id}/metadata'
	body = f'''
	<MetadataDocument xmlns="http://xml.vidispine.com/schema/vidispine">
        <timespan end="+INF" start="-INF">
            <group>
                <name>ateme</name>
                <field>
                    <name>ateme_vs_jobid</name>
                    <value>{job_id}</value>
                </field>
            </group>
        </timespan>
    </MetadataDocument>
    '''
	headers = {
		'Accept': 'application/xml',
		'Authorization': vs_auth
    }
	put_response = requests.put(put_url, headers=headers, data=body)
	if put_response.status_code != 200:
		print(f'Failed to put new Ateme job ID {job_id} for item {old_item_id}! Aborting.')
		exit(1)
	else:
		print(f'Successfully put new Ateme job ID {job_id} for item {old_item_id}.\n\n\n')
		return True
	
def get_and_delete_external_id(vs,vs_auth,old_item_id):
	get_url = f'{vs}API/item/{old_item_id}/metadata;field=__external_id'
	headers = {
		'Accept': 'application/xml',
		'Authorization': vs_auth
	}
	get_response = xml_prep(requests.get(get_url, headers=headers))
	if get_response.find('item/metadata/timespan/field/value') is None:
		print(f'No external ID found in item {old_item_id}! ACTIVATING PLAN B.')
		return False
	else:
		external_id = get_response.find('item/metadata/timespan/field/value').text
		del_url = f'{vs}API/item/{old_item_id}/external-id'
		del_response = requests.delete(del_url, headers=headers)
		if del_response.status_code != 200:
			print(f'Failed to delete external ID for item {old_item_id}! Aborting.')
			exit(1)
		else:
			print(f'Successfully deleted external ID for item {old_item_id}.')
		return external_id

def get_external_from_uri(vs,vs_auth,item_id):
	uri_url = f'{vs}API/item/{item_id}/metadata;field=originalUri'
	headers = {
		'Accept': 'application/xml',
		'Authorization': vs_auth
	}
	uri_response = xml_prep(requests.get(uri_url, headers=headers))
	original_uri = uri_response.find('item/metadata/timespan/field/value').text
	uri_external_id = original_uri.replace('file:///mnt/Mezz/mam/prod/import/transcodes/ateme_transcodes/','').split('/')[0]
	return uri_external_id

def search_for_external_id(vs,vs_auth,external_id):
	search_url = f'{vs}API/item'
	headers = {
		'Accept': 'application/xml',
		'Content-type': 'application/xml',
		'Authorization': vs_auth
	}
	body = f'''
    <ItemSearchDocument version="2"  xmlns="http://xml.vidispine.com/schema/vidispine">
        <intervals>generic</intervals>
        <field>
            <name>__external_id</name>
            <value>{external_id}</value>
        </field>
    </ItemSearchDocument>
    '''
	response = xml_prep(requests.put(search_url, headers=headers, data=body))
	if response.find('hits').text != '1':
		hits = response.find('hits').text
		print(f'Found {hits} items with external ID {external_id}. We were expecting 1. CHECK YOUR SHIT.')
		exit(1)
	else:
		return response.find('item').attrib['id']

def delete_bad_item(vs,vs_auth,item_id_with_external):
	del_url = f'{vs}API/item/{item_id_with_external}'
	headers = {
		'Accept': 'application/xml',
		'Authorization': vs_auth
	}
	del_response = requests.delete(del_url, headers=headers)	
	if del_response.status_code != 200:
		print(f'Failed to delete {item_id_with_external}! Aborting. Status code: {del_response.status_code}')
		exit(1)
	else:
		print(f'Successfully deleted {item_id_with_external}. Please take 30 seconds to reflect.')
		time.sleep(30)
		return True
	
def parse_external_id(external_id):
	id_list = external_id.split('_')
	if len(id_list[-1]) != 3:
		print('Something went wrong when extracting language metadata. Aborting.')
		exit(1)
	if len(id_list[-2]) == 3:
		# this is a dual-language item
		return [id_list[-2],id_list[-1]]
	else:
		return [id_list[-1]]

def return_to_placeholder(vs,vs_auth,old_item_id):
	url = f'{vs}API/job?type=RETURN_TO_PLACEHOLDER&jobmetadata=itemId={old_item_id}&priority=HIGH'
	headers = {
		'Accept': 'application/xml',
		'Authorization': vs_auth
	}
	response = requests.post(url, headers=headers)
	if response.status_code != 200:
		print(f'Failed to return item {old_item_id} to placeholder! Aborting.')
		exit(1)
	else:
		print(f'Successfully returned item {old_item_id} to placeholder.')
		return True

def ateme_submit(vs,vs_auth,old_item_id,parent_id,caption_id,transcode_profile,languages):
	if caption_id == '':
		caption_metadata = ''
	else:
		caption_metadata = f'&jobmetadata=caption_id={caption_id}'
	if len(languages) == 1:
		language_metadata = f'track_1_lang={languages[0]}'
	elif len(languages) == 2:
		language_metadata = f'track_1_lang={languages[0]}&jobmetadata=track_2_lang={languages[1]}'
	ateme_url = f'{vs}API/job?type=ind_ateme_transcode&jobmetadata=itemId={parent_id}{caption_metadata}&jobmetadata=transcode_profile={transcode_profile}&jobmetadata={language_metadata}&jobmetadata=placeholder_item_id={old_item_id}'
	headers = {
		'Accept': 'application/xml',
		'Authorization': vs_auth
	}
	print(f'Submitting call:\n{ateme_url}')
	submit_response = requests.post(ateme_url, headers=headers)
	if submit_response.status_code != 200:
		print(f'Failed to submit transcode job for item {old_item_id}! Aborting.')
		exit(1)
	else:
		job_id = xml_prep(submit_response).find('jobId').text
		print(f'Successfully submitted transcode job for item {old_item_id}. Job ID: {job_id}')
		return job_id

def csv_parse():
	list_list = []
	with open('great_replacement.csv', 'r') as file:
		csv_file = csv.reader(file)
		for line in csv_file:
			list_list.append(line)
	return list_list[1:]

def main(environment,proxy_config_file,script_file_name):
	user = getpass.getuser()
	logging.info(f'{environment}: COMMENCING: {script_file_name} executed by {user}')
	proxy_config = ET.parse(proxy_config_file)
	vs,vs_auth = get_variables_from_config(environment,proxy_config)
	list_list = csv_parse()
	for list in list_list:
		old_item_id = list[0]
		parent_id = list[1]
		caption_id = list[2]
		transcode_profile = list[3]
		delete_md5_hash(vs,vs_auth,old_item_id)
		delete_ateme_job_id(vs,vs_auth,old_item_id)
		external_id = get_and_delete_external_id(vs,vs_auth,old_item_id)
		if not external_id:
			uri_external_id = get_external_from_uri(vs,vs_auth,old_item_id)
			print(f'{old_item_id} External ID from URI: {uri_external_id}')
			item_id_with_external = search_for_external_id(vs,vs_auth,uri_external_id)
			print(f'External ID {uri_external_id} found in item {item_id_with_external}.')
			decision = input(f'Do you want to delete item {item_id_with_external}? (y/n)')
			if decision.lower() == 'y':
				return_to_placeholder(vs,vs_auth,item_id_with_external)
				print('Waiting 60 seconds for placeholder...')
				time.sleep(60)
				delete_bad_item(vs,vs_auth,item_id_with_external)
			else:
				exit(1)
			external_id = uri_external_id
		languages = parse_external_id(external_id)
		return_to_placeholder(vs,vs_auth,old_item_id)
		print('Waiting 60 seconds for placeholder...')
		time.sleep(60)
		job_id = ateme_submit(vs,vs_auth,old_item_id,parent_id,caption_id,transcode_profile,languages)
		put_new_ateme_job_id(vs,vs_auth,old_item_id,job_id)
	return True

main(environment,proxy_config_file,script_file_name)
exit(0)