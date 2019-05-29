import boto3
from botocore.exceptions import ClientError
import sys
import backoff
import pymysql
import click

MAX_TRIES = 5

metric_data = """
MetricData = [
    {
        'MetricName': 'primary-keys-for-db-rds',
        'Unit': 'Count',
        'Value': {{ primary_key_value }}
    },
],
Namespace = 'LogMetrics'
)
"""

class EC2BotoWrapper:
    def __init__(self):
        self.client = boto3.client("ec2")

    @backoff.on_exception(backoff.expo,
                          ClientError,
                          max_tries=MAX_TRIES)
    def describe_regions(self):
        return self.client.describe_regions()


class CWBotoWrapper:
    def __init__(self):
        self.client = boto3.client('cloudwatch')

    @backoff.on_exception(backoff.expo,
                          ClientError,
                          max_tries=MAX_TRIES)
    def list_metrics(self, *args, **kwargs):
        return self.client.list_metrics(*args, **kwargs)

    @backoff.on_exception(backoff.expo,
                          ClientError,
                          max_tries=MAX_TRIES)
    def put_metric_data(self, *args, **kwargs):
        return self.client.put_metric_data(*args, **kwargs)


class RDSBotoWrapper:
    def __init__(self, **kwargs):
        self.client = boto3.client("rds", **kwargs)

    @backoff.on_exception(backoff.expo,
                          ClientError,
                          max_tries=MAX_TRIES)
    def describe_db_instances(self):
        return self.client.describe_db_instances()



def get_rds_from_all_regions():
    """
    Gets a list of RDS instances across all the regions and deployments in AWS

    :returns:
    list of all RDS instances across all the regions
        [
            {
                'name': name of RDS,
                'Endpoint': Endpoint of RDS
                'Port': Port of RDS
            }
        ]
    name (string)
    Endpoint (string)
    Port (string)
    """
    client_region = EC2BotoWrapper()
    rds_list = []
    try:
        regions_list = client_region.describe_regions()
    except ClientError as e:
        print("Unable to connect to AWS with error :{}".format(e))
        sys.exit(1)
    for region in regions_list["Regions"]:
        client = RDSBotoWrapper(region_name=region["RegionName"])
        response = client.describe_db_instances()
        for instance in response.get('DBInstances'):
            temp_dict = dict()
            temp_dict["name"] = instance["DBInstanceIdentifier"]
            temp_dict["Endpoint"] = instance.get("Endpoint").get("Address")
            temp_dict["Port"] = instance.get("Port")
            rds_list.append(temp_dict)
    return rds_list


def check_table_growth(rds_list, username, password):
    """
    :param rds_list:
    :param username:
    :param password:

    :returns:
         Return list of all tables that cross threshold limit
              [
                  {
                    "name": "string",
                    "db": "string",
                    "table": "string",
                    "size": "string",
                  }
              ]
    """
    try:
        table_list = []
        for item in rds_list:
            rds_host_endpoint = item["Endpoint"]
            rds_port = item["Port"]
            connection = pymysql.connect(host=rds_host_endpoint,
                                         port=rds_port,
                                         user=username,
                                         password=password)
            # prepare a cursor object using cursor() method
            cursor = connection.cursor()
            # execute SQL query using execute() method.
            cursor.execute("""
            SELECT 
            INDEX_LENGTH, TABLE_NAME, AUTO_INCREMENT, TABLE_ROWS 
            FROM 
            information_schema.TABLES 
            ORDER BY 
            index_length DESC;
            """)
            rds_result = cursor.fetchall()
            cursor.close()
            connection.close()

            for tables in rds_result:
                temp_dict = dict()
                temp_dict["rds"] = item["name"]
                temp_dict["index_length"] = tables[0]
                temp_dict["table_name"] = tables[1]
                temp_dict["rows"] = tables[2]
                table_list.append(temp_dict)
        return table_list
    except Exception as e:
        print("Please see the following exception ", e)
        sys.exit(1)


@click.command()
@click.option('--username', envvar='USERNAME', required=True)
@click.option('--password', envvar='PASSWORD', required=True)
def controller(username, password):
    """
    calls other function and calculate the results
    :param username: username for the RDS.
    :param password: password for the RDS.
    :return: None
    """

    # get list of all the RDSes across all the regions and deployments
    rds_list = get_rds_from_all_regions()
    table_list = check_table_growth(rds_list, username, password)
    if len(table_list) > 0:
        format_string = "{:<40}{:<20}{:<50}{}"
        print(format_string.format("RDS Name","Database Name", "Table Name", "Size"))
        for items in table_list:
            print(format_string.format(items["rds"], items["db"], items["table"], str(items["size"]) + " MB"))
        exit(1)
    exit(0)
