import requests
import xml.etree.ElementTree as ET
from base64 import b64encode
import time
import json
from datetime import datetime

# This package replaces the original eng_vs.py
# changes include importing logger from main
# also all functions use 

# import the crt_file from main so that we can verify the https
from __main__ import crt_file

# import the logger from main so we can log stuff without it being passed in the functions
# make sure that logger is created in main before importing this module
from __main__ import logger

# HELPER FUNCTIONS

def get_basic_auth(username,password):
	token = b64encode(f"{username}:{password}".encode('utf-8')).decode("ascii")
	basic_auth = f'Basic {token}'
	return basic_auth

def get_token_no_auto_refresh(vs,basic_auth,seconds) -> dict:
	# this function uses basic auth to get a vs token which will expire after X seconds
	# the output dict will include the token, expiry time, and token_life so we know how long to renew it
	# {'token':'/5ZtWKVetT14+DuyXW+d2zx9N7vNp3Ei0iWFwhWG', 'expiry':1714524862.839222, 'token_life': 60, 'vs': vs}
	auth_time = time.time()
	expires = auth_time + seconds
	token_auth_dict = {}
	url = f'{vs}API/token?seconds={seconds}&autoRefresh=false'
	headers = {
		'Accept': 'application/json',
		'Authorization': basic_auth
	}
	response = requests.request("GET", url, headers=headers, verify=crt_file)
	if response.status_code >= 300:
		logger.error(f'Could not get Vidispine token. status code {response.status_code}')
		exit(1)
	else:
		logger.info('Created Vidispine token.')
		auth_res_json = response.json()
		token_auth_dict['token'] = auth_res_json['token']
		token_auth_dict['expiry'] = expires
		token_auth_dict['token_life'] = seconds
		token_auth_dict['vs'] = vs
		return token_auth_dict

def get_auto_refresh_token(vs,basic_auth,seconds) -> dict:
	# this function uses basic auth to get a vs token which will expire after X seconds if it isn't used
	# for each use it will auto refresh
	# use this type of token in applications that are long lasting and frequently hit the api
	# the output dict will include the token, expiry time, and token_life so we know how long to renew it
	# the output dict also contains the vs base_url where it was originally called from
	# {'token':'/5ZtWKVetT14+DuyXW+d2zx9N7vNp3Ei0iWFwhWG', 'expiry':1714524862.839222, 'token_life': 60, 'vs': vs}
	auth_time = time.time()
	expires = auth_time + seconds
	token_auth_dict = {}
	url = f'{vs}API/token?seconds={seconds}&autoRefresh=true'
	headers = {
		'Accept': 'application/json',
		'Authorization': basic_auth
	}
	response = requests.request("GET", url, headers=headers, verify=crt_file)
	if response.status_code >= 300:
		logger.error(f'Could not get Vidispine token. status code {response.status_code}')
		exit(1)
	else:
		logger.info('Created Vidispine token.')
		auth_res_json = response.json()
		token_auth_dict['token'] = auth_res_json['token']
		token_auth_dict['expiry'] = expires
		token_auth_dict['token_life'] = seconds
		token_auth_dict['vs'] = vs
		return token_auth_dict

def refresh_token(token_auth_dict) -> dict:
	# receives a token_auth_dict
	# gets a new token with the existing token
	# returns a new token_auth_dict
	# WARNING uses the same vs url as previous auth i.e. if http://prod-vs:8080/ was specified, it stays with that on the refresh
	# assumes we are working with a non autoRefresh token and producing a new one.
	new_token_auth_dict = {}
	auth_time = time.time()
	seconds = token_auth_dict['seconds']
	expires = auth_time + seconds
	vs = token_auth_dict["vs"]
	url = f'{vs}API/token?seconds={seconds}&autoRefresh=false'
	headers = {
		'Accept': 'application/json',
		'Authorization': f'token {token_auth_dict["token"]}'
	}
	response = requests.request("GET", url, headers=headers, verify=crt_file)
	if response.status_code >= 300:
		logger.error(f'Could not refresh Vidispine token. status code {response.status_code}')
		exit(1)
	else:
		logger.info('Refreshed Vidispine token.')
		auth_res_json = response.json()
		new_token_auth_dict['token'] = auth_res_json['token']
		new_token_auth_dict['expiry'] = expires
		new_token_auth_dict['token_life'] = seconds
		new_token_auth_dict['vs'] = vs
		return token_auth_dict

def xml_prep(res):
	# prepare a VS xml for parsing with ET
	res = res.content
	res = res.decode(encoding='utf-8', errors='strict')
	# because I hate dealing with the namespace in ET
	res = res.replace(' xmlns=\"http://xml.vidispine.com/schema/vidispine\"', "")
	res = res.encode(encoding='utf-8', errors='strict')
	res = ET.fromstring(res)
	return res

def status_check(vs_token_data, job_id):
	vs = vs_token_data['vs']
	token = vs_token_data["token"]
	url = f'{vs}API/job/{job_id}'
	headers = {
		'Authorization': f'token {token}'
	}
	response = requests.get(url, headers=headers, verify=crt_file)
	status_doc = xml_prep(response)
	return status_doc.find('status').text


# ITEM FUNCTIONS

def search_items(vs_token_data,search_doc) -> list:
	# use an auto refresh token if this is a long list being composed
	vs = vs_token_data["vs"]
	token = vs_token_data["token"]
	url = f'{vs}API/item'
	headers = {
		'Accept': 'application/xml',
		'Content-type': 'application/xml',
		'Authorization': f'token {token}'
	}
	data = search_doc
	response = requests.request("PUT", url, headers=headers, data=data, verify=crt_file)
	item_list_doc = xml_prep(response)
	hits = int(item_list_doc.find('hits').text)
	logger.info(f'There are {str(hits)} hits returned in this search.')
	logger.info('Compiling list of items.')
	number = 1000
	first = 1
	item_list = []
	while hits >= first:
		url = vs+'API/item;first=%s;number=%s' %(str(first),str(number))
		response = requests.request("PUT", url, headers=headers, data=data, verify=crt_file)
		items = xml_prep(response)
		for item in items.findall('item'):
			item_id = item.attrib['id']
			item_list.append(item_id)
		first = first + number
	return item_list

def put_item_metadata(vs_token_data,item_id,metadata_doc):
	# metadata_doc can be an xml or a dict which will be converted to a json string
	# return status_code
	vs = vs_token_data["vs"]
	token = vs_token_data["token"]
	url = f'{vs}API/item/{item_id}/metadata'
	if isinstance(metadata_doc,dict):
		metadata_doc = json.dumps(metadata_doc)
		headers = {
			'Content-Type': 'application/json',
			'Authorization': f'token {token}'
		}
	else:
		headers = {
			'Content-Type': 'application/xml',
			'Authorization': f'token {token}'
		}
	response = requests.request("PUT", url, headers=headers, data=metadata_doc, verify=crt_file)
	if response.status_code >= 300:
		logger.error('PUT vs metadata status: %s content: %s' % (str(response.status_code),response.text))
		return response.status_code
	else:
		logger.info('PUT vs metadata status: %s' % (str(response.status_code)))
		return response.status_code

def is_mapped(vs_token_data,item_id):
	vs = vs_token_data["vs"]
	token = vs_token_data["token"]
	url = f'{vs}API/item/{item_id}/metadata;field=indab_master_id'
	headers = {
		'Accept': 'application/xml',
		'Authorization': f'token {token}'
	}
	response = requests.request("GET", url, headers=headers, verify=crt_file)
	metadata = xml_prep(response)
	try:
		indab_master_id = metadata.find('item/metadata/timespan/group/field/value').text
		logger.info(f'Found value of {indab_master_id} in indab_master_id field.')
		if indab_master_id == '0' or indab_master_id == '':
			return False
		else:
			return True
	except AttributeError:
		# doesn't have the field
		return False

def get_system_metadata_value(vs_token_data,item_id,field) -> str:
	# returns a string of the system metadata value
	# returns False if it can't find it
	vs = vs_token_data["vs"]
	token = vs_token_data["token"]
	url = f'{vs}API/item/{item_id}/metadata;field={field}'
	headers = {
		'Accept': 'application/xml',
		'Authorization': f'token {token}'
	}
	response = requests.request("GET", url, headers=headers, verify=crt_file)
	metadata = xml_prep(response)
	try:
		metadata_value = metadata.find('item/metadata/timespan/field/value').text
		logger.info(f'Found value of {metadata_value} in {field} field.')
		return metadata_value
	except AttributeError:
		# doesn't have the field
		logger.warning(f'Did not find metadata in {field} field.')
		return False

def get_group_metadata_value(vs_token_data,item_id,field) -> str:
	# returns a string from a group metadata value
	# returns False if it can't find it
	vs = vs_token_data["vs"]
	token = vs_token_data["token"]
	url = f'{vs}API/item/{item_id}/metadata;field={field}'
	headers = {
		'Accept': 'application/xml',
		'Authorization': f'token {token}'
	}
	response = requests.request("GET", url, headers=headers, verify=crt_file)
	metadata = xml_prep(response)
	try:
		groups = metadata.findall('item/metadata/timespan/group')
		metadata_value = ''
		for group in groups:
			if group.find('field/name').text == field:
				metadata_value = group.find('field/value').text
				logger.info(f'Found value of {metadata_value} in {field} field.')
				break
		if metadata_value == '' or metadata_value == None:
			logger.warning(f'Metadata field/value is empty in {field} field.')
			return False
		else:
			return metadata_value
	except AttributeError:
		# doesn't have the field
		logger.warning(f'Metadata field/value not found in {field} field.')
		return False

def delete_item(vs_token_data,item_id):
	vs = vs_token_data["vs"]
	token = vs_token_data["token"]
	url = f'{vs}API/item/{item_id}'
	headers = {
		'Authorization': f'token {token}'
	}
	response = requests.request("DELETE", url, headers=headers, verify=crt_file)
	if response.status_code < 300:
		logger.info(f'Item ID {item_id} deleted.')
	else:
		logger.warning(f'Item ID {item_id} NOT deleted. status code: {response.status_code}')
		logger.warning(f'{response.text}')
	return response.status_code

def get_md5(vs_token_data,item_id):
	md5 = get_group_metadata_value(vs_token_data,item_id,'original_shape_mi_original_shape_mi_md5_hash')
	if md5:
		return md5
	else:
		for field in ['__shapetag_original_hash','minidam_information_checksum']:
			md5 = get_system_metadata_value(vs_token_data,item_id,field)
			if md5 and md5 != '':
				return md5
	return False

def make_group_metadata_doc(vs_group,vs_field,vs_value):
	metadata = {
		"timespan": [
			{
				"start": "-INF",
				"end": "+INF",
				"group": [
					{
						"name": vs_group,
						"field": [
							{
								"name": vs_field,
								"value": [
									{
										"value": vs_value
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

def determine_run_time(token_data, item_id, workflow, env):
	logger.warning(f'Starting Run Time Update for {item_id} {workflow} in {env} environment')
	workflows = {
		'qc':
		{'start':'aggregate_test_start','end':'aggregate_test_end','group':'aggregate_test','field':'aggregate_test_runtime'},
		'fileinfo':
		{'start':'file_information_start','end':'file_information_end','group':'file_information','field':'file_information_runtime'}
	}

	# check for field presence
	start_time = get_group_metadata_value(token_data,item_id,workflows[workflow]['start'])
	end_time = get_group_metadata_value(token_data,item_id,workflows[workflow]['end'])
  
	if start_time == None or end_time == None:
		logger.warning('Missing start or end time')
	exit(0)

	start_time = iso8601.parse_date(start_time)
	logger.warning(f'Start time is {start_time}')

	end_time = iso8601.parse_date(end_time)
	logger.warning(f'End time is {end_time}')

	run_time = end_time - start_time
	logger.warning(f'Running time is {run_time.seconds} seconds')

	metadata_document = {
		"timespan": [{"start": "-INF","end": "+INF",
		"group": [{"name": workflows[workflow]['group'],
		"field": [{"name": workflows[workflow]['field'],
		"value": [{"value": str(run_time.seconds)}]}]}]}]
	}

	u = put_item_metadata(token_data,item_id,metadata_document)
	logger.warning(f'Updated Runtime as {str(run_time.seconds)}. Status code: {u}')

	asset_type = get_group_metadata_value(token_data,item_id,'file_information_asset_type')

	if asset_type.lower() == 'video' and workflow == 'qc':
		duration = float(get_system_metadata_value(token_data,item_id,'durationSeconds'))
		percent = round(run_time.seconds / duration,2)
		metadata = {
			"timespan": [{"start": "-INF","end": "+INF",
			"group": [{"name": 'aggregate_test',
			"field": [{"name": 'aggregate_test_realtime',
			"value": [{"value": str(percent)}]}]}]}]
		}
		u = put_item_metadata(token_data,item_id,metadata)
		logger.warning(f'Updated Realtime as {percent}. Status code: {u}')
		logger.warning('THE END.')
		return True

def build_json(token_data, item_id, env):
	report = {'qc_report':{'title':'','aggregate_result':'','file_name':'','section':[]}}

	logger.warning('Started Aggregate Json Builder')

	if sys.platform == 'win32':
		template = ET.parse('M:\\mam\\admin\\integrations\\autoqc\\autoQC_test_results_config.xml')
	elif sys.platform == 'darwin':
		template = ET.parse('/Volumes/Mezz/mam/admin/integrations/autoqc/autoQC_test_results_config.xml')
	else:
		template = ET.parse('/mnt/Mezz/mam/admin/integrations/autoqc/autoQC_test_results_config.xml')

	logger.warning('Successfully parsed xml')

	if env == 'prod':
		target_system = 'production'
	else:
		target_system = env

	subtype = get_group_metadata_value(token_data,item_id,'file_information_subtype')

	if 'mezz' in subtype.lower():
		subtype = 'mezz'
		title = 'Mezzanine Auto QC Report'
	elif 'deriv' in subtype.lower():
		subtype = 'deriv'
		title = 'Derivative Auto QC Report'
	else:
		logger.error(f'Invalid Subtype {subtype}')
		exit(0)
	logger.warning(f'Subtype: {subtype}')

	aggregate_result = get_group_metadata_value(token_data,item_id,'aggregate_test_result')
	file_name = get_system_metadata_value(token_data,item_id,'originalFilename')

	report['qc_report']['title'] = title
	report['qc_report']['aggregate_result'] = aggregate_result.upper()
	report['qc_report']['file_name'] = file_name
	report['qc_report']['section'] = []

	for x in template.findall('system'):
		if x.attrib['type'] == target_system:
			system = x

	for x in system.findall('report'):
		if x.attrib['type'] == subtype:
			subtype_report = x

	for x in subtype_report.findall('section'):
		s = {'sub_section':[],'_name':x.attrib['name']}
		for y in x.findall('sub_section'):
			t = {'test':[],'_name':y.attrib['name']}
			for z in y.findall('test'):
				result = get_group_metadata_value(token_data,item_id,z.find('result_source').text)
				if result:
					description = get_group_metadata_value(token_data,item_id,z.find('description_source').text)
					r = {'_name':z.attrib['name'],'result':result.upper(),'description':description}
					t['test'].append(r)
			s['sub_section'].append(t)
		report['qc_report']['section'].append(s)

	logger.warning('Filled JSON')

	metadata_update_doc = {
		"timespan": [{"start": "-INF","end": "+INF",
		"group": [{"name": 'aggregate_test',
		"field": [{"name": 'aggregate_test_results_json',
		"value": [{"value": json.dumps(report)}]}]}]}]
	}

	u = put_item_metadata(token_data,item_id,metadata_update_doc)
	logger.warning(f'Update response code: {u}')
	return True

# SHAPE FUNCTIONS

def get_shape_ids(vs: str, token: str, item_id: str, shapetag: str) -> list:
	'''
	this function retrieves a URIListDocument that contains the VX ids of the
	shapes as "uri" elements.
	get each VX id of the requested shape tag and construct a list
	'''
	url = f'{vs}API/item/{item_id}/shape?tag={shapetag}'
	headers = {
		'Accept': f'application/json',
		'Authorization': f'token {token}'
	}
	try:
		response = requests.request("GET", url, headers=headers, verify=crt_file)
		response.raise_for_status()  # Raises an HTTPError if the response was unsuccessful
		uri_list_doc = response.json()
	except HTTPError as http_err:
		logger.error(f'HTTP error occurred: {http_err}', extra=extras)
		exit(1)
	except Exception as err:
		logger.error(f'Other error occurred: {err}', extra=extras)
		exit(1)
	# make list to return
	shape_ids = []
	if "uri" in uri_list_doc:
		for uri in uri_list_doc["uri"]:
			shape_ids.append(uri)
		return shape_ids
	else:
		logger.info(f"Shape tag {shapetag}, not found in item {item_id}")
		return shape_ids

def get_shape_document(vs: str, token: str, item_id: str, shapetag: str) -> list:
	url = f'{vs}API/item/{item_id}?content=shape&tag={shapetag}'
	headers = {
		'Authorization': f'token {token}'
	}
	try:
		response = requests.get(url, headers=headers, verify=crt_file)
		response.raise_for_status()  # Raises an HTTPError if the response was unsuccessful
		return xml_prep(response)
	except HTTPError as http_err:
		logger.error(f'HTTP error occurred: {http_err}', extra=extras)
		exit(1)
	except Exception as err:
		logger.error(f'Other error occurred: {err}', extra=extras)
		exit(1)

def download_from_s3(vs_token_data,shape,target_storage,s3_storage,item_id,original_filename):
	# expects shape to be xml prepped
	vs = vs_token_data['vs']
	token = vs_token_data['token']
	headers = {
		'Authorization': f'token {token}'
	}
	file_id = find_storage_id(shape, s3_storage, 'file')	
	current_storage = find_storage_id(shape, s3_storage, 'storage')
	state = check_file_state(vs_token_data,current_storage,file_id)
	if state not in ['CLOSED','ARCHIVED']:
		return False
	url = f'{vs}API/storage/{current_storage}/file/{file_id}/storage/{target_storage}?move=false&jobmetadata=ind_filename={original_filename}&jobmetadata=itemId={item_id}'
	download = requests.post(url,headers=headers)
	job_doc = xml_prep(download)
	return job_doc.find('jobId').text

def shape_presence(vs_token_data,item_id,shapetag):
	vs = vs_token_data['vs']
	token = vs_token_data['token']
	headers = {
		'Authorization': f'token {token}'
	}
	metadata_url = f'{vs}API/item/{item_id}?content=metadata&terse=true'
	metadata = xml_prep(requests.get(metadata_url,headers=headers))
	for field in metadata.findall('field'):
		if field.find('name').text == 'shapeTag':
			for shape in field.findall('value'):
				if shape.text == shapetag:
					return True
	return False

def handle_bad_audio(vs_token_data, item_id, audio_profile_number, env):
    descriptions = {
        '998':'Stems',
        '999':'Unsupported audio format'
    }
    if audio_profile_number not in descriptions:
        logger.error(f'The provided audio profile number {audio_profile_number} is not actually bad!')
        exit(1)
    time = f'{datetime.isoformat(datetime.now())}-04:00'
    subtype = get_group_metadata_value(vs_token_data,item_id,'file_information_subtype')
    if subtype == None:
        logger.error('Subtype not found!')
        exit(1)
    if 'mezz' in subtype.lower():
        subtype = 'mezz'
    elif 'deriv' in subtype.lower():
        subtype = 'deriv'
    else:
        logger.error(f'Weird subtype! {subtype}')
        exit(1)
    
    updates = {
        f'{subtype}_wf_orig':[('status','Completed'),('audio_profile_status','Completed'),('current_process','None'),('audio_profile_end',time)],
        f'{subtype}_qc_orig_audio_profile':[('number',audio_profile_number),('description',descriptions[audio_profile_number])],
        f'{subtype}_qc_orig_category_results':[('audio_profile','Fail'),('audio_profile_description',f'WARNING: {descriptions[audio_profile_number]}')],
        'aggregate_test':[('status','Completed'),('end',time),('date',time),('result','Fail')]
    }

    for group in updates:
        for dataset in updates[group]:
            vs_group = group
            vs_field = f'{group}_{dataset[0]}'
            vs_value = dataset[1]
            logger.warning(f'Metadata update: group {vs_group}, field {vs_field}, value {vs_value}')
            metadata = {"timespan": [{"start": "-INF","end": "+INF",
                                     "group": [{"name": vs_group,
                                                "field": [{"name": vs_field,
                                                           "value": [{"value": vs_value}]}]}]}]}
            u = put_item_metadata(vs_token_data,item_id,metadata)
            logger.warning(f'Update status code: {u}')
            
    determine_run_time(vs_token_data, item_id, 'qc', env)
    build_json(item_id, env)
    return True




# STORAGE FUNCTIONS

def find_storage_id(shape, storage_type, target):
	# expects shape to be xml prepped
	for file in shape.findall('.//file'):
		if file.find('storage').text in storage_type:
			if target == 'file':
				result = file.find('id').text
			elif target == 'storage':
				result = file.find('storage').text
			return result

def get_storage_groups(vs_token_data,group_name):
	# returns list of all ID values connected to a storage group name
	vs = vs_token_data["vs"]
	token = vs_token_data["token"]
	url = f'{vs}API/storage/storage-group/{group_name}'
	headers = {
		'Accept': 'application/xml',
		'Authorization': f'token {token}'
	}
	response = requests.get(url, headers=headers, verify=crt_file)
	results = xml_prep(response)
	storage_ids = []
	for storage in results.findall('storage'):
		storage_ids.append(storage.find('id').text)
	return storage_ids

def get_storage_id_from_name(vs_token_data,storage_name) -> str:
	# use the storage name to locate and return the storage id
	vs = vs_token_data["vs"]
	token = vs_token_data["token"]
	url = f'{vs}API/storage'
	headers = {
		'Accept': 'application/xml',
		'Authorization': f'token {token}'
	}
	response = requests.request("GET", url, headers=headers, verify=crt_file)
	#print(response.status_code)
	storage_list_doc = xml_prep(response)
	storages = []
	for storage in storage_list_doc.findall('storage'):
		for field in storage.findall('metadata/field'):
			if field.find('key').text == 'name':
				name = field.find('value').text
				if name == storage_name:
					storage_id = storage.find('id').text
					return storage_id

def storage_presence(vs_token_data,item_id,storage,shapetag='original'):
	vs = vs_token_data["vs"]
	token = vs_token_data["token"]
	shape = get_shape_document(vs, token, item_id, shapetag)
	for file in shape.findall('.//file'):
		if isinstance(storage, list) and file.find('storage').text in storage:
			return True
		elif isinstance(storage, str) and file.find('storage').text == storage:
			return True
	return False

def current_storage_id(vs_token_data,item_id,storage_list,shapetag='original'):
	for storage in storage_list:
		if storage_presence(vs_token_data,item_id,storage,shapetag):
			return storage
	return False

def delete_locks(vs_token_data,file_id):
	# delete all locks on a file
	vs = vs_token_data["vs"]
	token = vs_token_data["token"]
	url = f'{vs}API/storage/file/{file_id}/deletion-lock'
	headers = {
		'Accept': 'application/xml',
		'Authorization': f'token {token}'
	}
	response = requests.request("GET", url, headers=headers, verify=crt_file)
	deletion_locks = xml_prep(response)
	if len(deletion_locks) > 0:
		index = 1
		while index <= len(deletion_locks):
			lock_id = deletion_locks.find(f'lock[{index}]/id').text
			delete_lock(vs,vs_auth,lock_id)
			index += 1
		logger.info(f'all locks deleted for {file_id}.')

def delete_lock(vs_token_data,lock_id):
	# partner function to delete_locks
	vs = vs_token_data["vs"]
	token = vs_token_data["token"]
	url = f'{vs}API/deletion-lock/{lock_id}'
	headers = {
		'Accept': 'application/xml',
		'Authorization': f'token {token}'
	}
	response = requests.request("DELETE", url, headers=headers, verify=crt_file)
	return response.status_code


def delete_unknown(vs_token_data,file_id):
	# deletes unknown files from solr
	vs = vs_token_data["vs"]
	token = vs_token_data["token"]
	url = f'{vs}API/configuration/properties/solrpath'
	headers = {
		'Accept': 'application/xml',
		'Authorization': f'token {token}'
	}
	response = requests.request("GET", url, headers=headers, verify=crt_file)
	res = xml_prep(response)
	solr = res.find('value').text
	solr_url = f'{solr}/update?commit=true'
	payload = f'<delete><query>entityId:{file_id} AND type:File</query></delete>'
	headers = {'Content-Type': 'text/xml; charset=utf-8'}
	response = requests.request("POST", solr_url, headers=headers, data = payload)
	return True

def delete_file(vs_token_data,file_id):
	vs = vs_token_data["vs"]
	token = vs_token_data["token"]
	url = f'{vs}API/storage/file/{file_id}'
	headers = {
		'Accept': 'application/xml',
		'Authorization': f'token {token}'
	}
	response = requests.request("DELETE", url, headers=headers, verify=crt_file)
	if response.status_code < 300:
		logger.info(f'File ID {file_id} deleted.')
	else:
		logger.warning(f'File ID {file_id} NOT deleted. status code: {response.status_code}')
		logger.warning(f'{response.text}')
	return response.status_code

def check_file_state(vs_token_data,storage_id,file_id):
	vs = vs_token_data['vs']
	token = vs_token_data['token']
	headers = {
		'Authorization': f'token {token}'
	}
	r = requests.get(f'{vs}API/storage/{storage_id}/file/{file_id}',headers=headers)
	file_doc = xml_prep(r)
	return file_doc.find('state').text
	
def get_all_files_matching_state(vs_token_data,storage_id,file_state):
	vs = vs_token_data["vs"]
	token = vs_token_data["token"]
	url = f'{vs}API/storage/{storage_id}/file;number=10?state={file_state}'
	headers = {
		'Accept': 'application/xml',
		'Authorization': f'token {token}'
	}
	response = requests.request("GET", url, headers=headers, verify=crt_file)
	file_doc = xml_prep(response)
	hits = int(file_doc.find('hits').text)
	if hits > 0:
		logger.info(f'{str(hits)} hits found on storage {storage_id} for files in state {file_state}.')
		if hits > 1000:
			number = 10000
			first = 0
		else:
			number = hits
			first = 0
	else:
		logger.warning(f'No hits found on storage {storage_id} for files in state {file_state}.')
	files = []
	while first < hits:
		url = f'{vs}API/storage/{storage_id}/file;first={str(first)};number={str(number)}?state={file_state}'
		response = requests.request("GET", url, headers=headers, verify=crt_file)
		file_doc = xml_prep(response)
		for file in file_doc:
			file_state = file.find('state').text
			file_id = file.find('id').text
			if file_state == 'UNKNOWN':
				logger.warning(f'file id {file_id} is in the UNKNOWN state. Attempting to delete.')
				delete_unknown(vs,vs_auth,file_id)
				continue
			else:
				files.append(file_id)
		first = first + number
	return files





# JOBS

def update_job_metadata(vs_token_data,job_id,key,value):
	vs = vs_token_data["vs"]
	token = vs_token_data["token"]
	url = f'{vs}API/job/{job_id}/step/0/data'
	headers = {'Content-Type': "application/xml",'Accept': "application/xml",'Authorization': f'token {token}'}
	data = f'<SimpleMetadataDocument xmlns="http://xml.vidispine.com/schema/vidispine"><field><key>{key}</key><value>{value}</value></field></SimpleMetadataDocument>'
	put_response = requests.request("PUT", url, headers=headers, data=data, verify=crt_file)
	if put_response.status_code == 200:
		return True
	else:
		return False

def wait_for_job(vs_token_data,job_id):
	vs = vs_token_data["vs"]
	token = vs_token_data["token"]
	url = f'{vs}API/job/{job_id}'
	headers = {'Content-Type': 'application/xml','Accept': 'application/xml','Authorization': f'token {token}'}
	done = False
	logger.info(f'Checking job {job_id} status')
	while done == False:
		response = requests.request("GET", url, headers=headers, verify=crt_file)
		job_doc = xml_prep(response)
		status = job_doc.find('status').text
		if status == 'FINISHED':
			logger.info(f'Job {job_id} is FINISHED!')
			done = True
			return status
		elif status == 'FAILED_TOTAL':
			logger.error(f'Job {job_id} is FAILED_TOTAL!')
			return status
		elif status == 'ABORTED':
			logger.error(f'Job {job_id} is ABORTED!')
			return status
		else:
			logger.debug(f'Job {job_id} is in the {status} state!')
			time.sleep(5)
