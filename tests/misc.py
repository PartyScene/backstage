import requests

url = 'https://tnrhlb2p-8002.euw.devtunnels.ms//media/upload'

file_path = "C:/Users/User/Downloads/team-venus-removebg.png"  # Replace with the path to your file

headers = {'Authorization': 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpYXQiOjE3MzIwMTYxMDYsIm5iZiI6MTczMjAxNjEwNiwianRpIjoiYzkwMjU3YzYtY2E3OC00MTkwLTkyYjgtOTg1NzU3ZjhlNjUxIiwiZXhwIjoxNzMyMDE3MDA2LCJpZGVudGl0eSI6InRlc3RAdGVzdC5jb20iLCJmcmVzaCI6ZmFsc2UsInR5cGUiOiJhY2Nlc3MifQ.fJyLSbE1kMa70nKa3zWJjwNaLuX26zal2HkF3RkUyZY'}

with open(file_path, "rb") as file:
    files = {"file": (file_path.split("/")[-1], file, "image/png")}
    response = requests.post(url, headers = headers, files=files)
    print(response.status_code, response.text)
