#!/usr/bin/python3

import requests
headers = {
	'Content-type': 'application/json',
	'Authorization': 'Bearer 9fa71aeb9014e80ca8043fb385ca84a27b9cf8e7a1fa5600f6866a7647240cc8'
	}
url_status =  'https://ind-ateme.indemand.com/tf2181/api/jobs/730a12a9-768a-4df2-961b-26ff2dc50f35/state'
status_response = requests.get(url_status, headers=headers)
print(status_response.text)