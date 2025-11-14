#!/usr/bin/python3
import requests
import xml.etree.ElementTree as ET
import sys
import logging
import os
import getpass

'''
Get checksum from list
Search vidispine for item ID with checksum
Use item ID to get shape
Look for any file attached to shape
If file is in shape, item is in house
Check metadata for media_management_corrupt - if True, item is corrupt
If multiple items found, iterate
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

def get_shape_file(vs, vs_auth, item_id):
	url = f'{vs}API/item/{item_id}?content=shape&tag=original'
	headers = {
		'Accept': 'application/xml',
		'Authorization': vs_auth
	}
	response = xml_prep(requests.get(url, headers=headers))
	shape_file = response.find('shape/containerComponent/file')
	return shape_file

def item_from_checksum(vs, vs_auth, checksum):
	data = f'''
    <ItemSearchDocument xmlns="http://xml.vidispine.com/schema/vidispine">
        <intervals>generic</intervals>
            <group>
                <name>original_shape_mi</name>
                <field>
                    <name>original_shape_mi_original_shape_mi_md5_hash</name>
                    <value>{checksum}</value>
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
	multiples = False
	if hits > 1:
		print(f'WARNING: More than one item found with checksum {checksum}.')
		multiples = True
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
	
def main(environment,proxy_config_file,script_file_name):
	user = getpass.getuser()
	logging.info(f'{environment}: COMMENCING: {script_file_name} executed by {user}')
	proxy_config = ET.parse(proxy_config_file)
	vs,vs_auth = get_variables_from_config(environment,proxy_config)
	resultsfile = open("InHouse_Charter_Delta_250728.csv", "w+")
	resultsfile.write('Checksum,In House,Corrupt,Item ID\r')
	checksum_list = open('checksum_list.txt', 'r')
	for checksum in checksum_list:
		checksum = checksum.strip()
		print(checksum)
		item_list = item_from_checksum(vs, vs_auth, checksum)
		if not item_list:
			print(f'No item IDs found for {checksum}\r')
			resultsfile.write(f'{checksum},False,N/A,\r')
		else:
			usable_items = []
			for item in item_list:
				item = item.strip()
				corrupt = get_group_metadata_value(vs,vs_auth,item,'media_management_corrupt')
				if corrupt and corrupt.lower() == 'true':
					print(f'Item {item} is corrupt.')
				else:
					shape_presence = get_shape_file(vs, vs_auth, item)
					if shape_presence is None:
						print(f'Item {item} is not in house.')
					else:
						print(f'Item {item} is a usable item with checksum {checksum}.')
						usable_items.append(item)
			if len(usable_items) == 0:
				print(f'No usable items found for checksum {checksum}.\n')
				resultsfile.write(f'{checksum},N/A,N/A,\r')
			else:
				print(f'{len(usable_items)} usable items found for checksum {checksum}.')
				print(f'We are going with {max(usable_items)}.')
				resultsfile.write(f'{checksum},True,False,{max(usable_items)}\r')
	print('Finished.')

main(environment,proxy_config_file,script_file_name)
exit(0)
