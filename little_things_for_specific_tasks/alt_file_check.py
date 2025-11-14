#!/usr/bin/python3
'''
-Get item from list
-Get item's file_information_is_trailer value
-Check item's metadata for indab_master_id value
-If no master ID, item has no alts
-If master ID, search VS for items with that master ID
-Check metadata of each returned item for file_information_subtype_descriptor and file_information_is_trailer
-If is_trailer value doesn't match original, item is disqualified
-Compile list of qualified of files
    -Features must have file_information_subtype_descriptor value containing "CL_HD_MP2_15000"
    -Trailers can be SD or HD
-If list is empty, item has no children
-Otherwise, check items to make sure they're in house and not corrupt
-If multiple items pass checks, return item with highest ID
-If nothing passes checks, item has no children
'''
import xml.etree.ElementTree as ET
import sys
import logging
import os
import getpass
import requests



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

def search_for_spock(vs,vs_auth,group,field,value):
	data = f'''
    <ItemSearchDocument xmlns="http://xml.vidispine.com/schema/vidispine">
        <intervals>generic</intervals>
            <group>
                <name>{group}</name>
                <field>
                    <name>{field}</name>
                    <value>{value}</value>
                </field>
            </group>
    </ItemSearchDocument>
    '''
	url = vs+'API/item'
	headers = {
		'Accept': 'application/xml',
		'Content-type': 'application/xml',
		'Authorization': vs_auth
	}
	response = requests.request("PUT", url, headers=headers, data=data)
	item_list_doc = xml_prep(response)
	hits = int(item_list_doc.find('hits').text)
	number = 1000
	first = 1
	item_list = []
	while hits >= first:
		url = vs+'API/item;first=%s;number=%s' %(str(first),str(number))
		response = requests.request("PUT", url, headers=headers, data=data)
		items = xml_prep(response)
		for item in items.findall('item'):
			item_id = item.attrib['id']
			item_list.append(item_id)
		first = first + number
	if item_list == []:
		return False
	return item_list

def get_system_metadata_value(vs,vs_auth,item_id,field):
	# for ungrouped fields
	url = f'{vs}API/item/{item_id}/metadata;field={field}'
	headers = {
		'Accept': 'application/xml',
		'Authorization': vs_auth
	}
	response = xml_prep(requests.get(url, headers=headers))
	try:
		metadata_value = response.find('item/metadata/timespan/field/value').text
		return metadata_value
	except AttributeError:
		# doesn't have the field
		return False

def get_group_metadata_value(vs,vs_auth,item_id,field):
	# for fields in groups
	url = f'{vs}API/item/{item_id}/metadata;field={field}'
	headers = {
		'Accept': 'application/xml',
		'Authorization': vs_auth
	}
	response = xml_prep(requests.get(url, headers=headers))
	try:
		groups = response.findall('item/metadata/timespan/group')
		metadata_value = ''
		for group in groups:
			if group.find('field/name').text == field:
				metadata_value = group.find('field/value').text
				break
		if metadata_value == '' or metadata_value == None:
			return False
		else:
			return metadata_value
	except AttributeError:
		# doesn't have the field
		return False

def get_shape_file(vs, vs_auth, item_id):
	url = f'{vs}API/item/{item_id}?content=shape&tag=original'
	headers = {
		'Accept': 'application/xml',
		'Authorization': vs_auth
	}
	response = xml_prep(requests.get(url, headers=headers))
	shape_file = response.find('shape/containerComponent/file')
	return shape_file

def main(environment,proxy_config_file,script_file_name):
	user = getpass.getuser()
	logging.info(f'{environment}: COMMENCING: {script_file_name} executed by {user}')
	proxy_config = ET.parse(proxy_config_file)
	vs,vs_auth = get_variables_from_config(environment,proxy_config)
	resultsfile = open("children_check.csv", "w+")
	resultsfile.write('Item ID,Alt ID,Alt Checksum,Alt Filename\r')
	item_list = open('potentialParents.txt', 'r')
	for item in item_list:
		item = item.strip()
		# get indab id and trailer info
		print(f'{item}')
		indab_master_id = get_group_metadata_value(vs,vs_auth,item,'indab_master_id')
		parent_trailer = get_group_metadata_value(vs,vs_auth,item,'file_information_is_trailer')
		if not indab_master_id or indab_master_id == '0':
			print(f'No Indab master ID found.')
		else:
			print(f'Indab master ID: {indab_master_id}')
			indab_master_list = search_for_spock(vs,vs_auth,'indab','indab_master_id',indab_master_id)
			alt_list = []
			for x in indab_master_list:
				# subtype/trailer check
				subtype = get_group_metadata_value(vs,vs_auth,x,'file_information_subtype_descriptor')
				if subtype and "CL_HD_MP2_15000" in subtype:
					alt_trailer = get_group_metadata_value(vs,vs_auth,x,'file_information_is_trailer')
					if alt_trailer == parent_trailer:
						# in house/corrupt check
						corrupt = get_group_metadata_value(vs,vs_auth,x,'media_management_corrupt')
						if corrupt and corrupt.lower() == 'true':
							print(f'Item {x} is corrupt.')
						else:
							shape_presence = get_shape_file(vs, vs_auth, x)
							if shape_presence is None:
								print(f'Item {x} is not in house.')
							else:
								print(f'Item {x} is a qualified CL_HD_MP2_15000 derivative.')
								alt_list.append(x)
			if len(alt_list) == 0:
				print(f'No HD alternates found for item {item}.\n')
				if parent_trailer and parent_trailer.lower() == 'true':					
					# look for SD trailers
					print(f'Item {item} is a trailer, so we will look for SD trailers')
					for x in indab_master_list:
						alt_trailer = get_group_metadata_value(vs,vs_auth,x,'file_information_is_trailer')
						if alt_trailer == parent_trailer:
							# in house/corrupt check
							corrupt = get_group_metadata_value(vs,vs_auth,x,'media_management_corrupt')
							if corrupt and corrupt.lower() == 'true':
								print(f'Item {x} is corrupt.')
							else:
								shape_presence = get_shape_file(vs, vs_auth, x)
								if shape_presence is None:
									print(f'Item {x} is not in house.')
								else:
									print(f'Item {x} is an SD trailer, which is the best we can do right now.')
								alt_list.append(x)
			else:
				print(f'{len(alt_list)} eligible alternates found for item {item}.')
				print(f'We are going with {max(alt_list)}.')
				alternate_item = max(alt_list)
				alt_checksum = get_group_metadata_value(vs,vs_auth,alternate_item,'original_shape_mi_original_shape_mi_md5_hash')
				alt_filename = get_system_metadata_value(vs,vs_auth,alternate_item,'originalFilename')
				print(f'{alt_filename}\n{alt_checksum}\n')
				resultsfile.write(f'{item},{alternate_item},{alt_checksum},{alt_filename}\r')
	print('Done.')

main(environment,proxy_config_file,script_file_name)
exit(0)