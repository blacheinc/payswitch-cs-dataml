"""
Script 1: Create and Upload Test JSON File to Blob Storage

Generates a JSON **array of rows** that mirror real XDS P45 JSON. Raw XDS does **not**
include ``applicant_context``; each uploaded row is only:

  { "consumer_full_report_45": <full P45 object> }

The inner object follows the same sections and field names as production samples
(response, subjectList, personalDetailsSummary, creditAgreementSummary[],
accountMonthlyPaymentHistory[], enquiryHistory[], etc.).

Uploads to the blob storage account (default container from BLOB_CONTAINER_NAME, usually ``data``).
"""

import json
import os
import sys
from pathlib import Path

# Try to import dotenv
try:
    from dotenv import load_dotenv
    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False
    print("⚠️  python-dotenv not installed. Will use environment variables only.")

from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential, AzureCliCredential

# Add parent directories to path
CURRENT_DIR = Path(__file__).parent
TRAINING_INGESTION_ROOT = CURRENT_DIR.parent

# Add paths for imports
if str(TRAINING_INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(TRAINING_INGESTION_ROOT))

# Load environment variables
if HAS_DOTENV:
    env_path = TRAINING_INGESTION_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)

from utils.training_key_vault_reader import (
    TrainingKeyVaultReader as KeyVaultReader,
    TrainingKeyVaultError as KeyVaultError,
)


def _monthly_payment_history_row(
    *,
    account_no: str,
    subscriber: str,
    date_account_opened: str,
    closed_date: str,
    last_updated: str,
    indicator_description: str,
    opening_balance: str,
    current_balance: str,
    instalment: str,
    amount_overdue: str,
) -> dict:
    """Single Consumer24MonthlyPayment row — same key layout as production XDS samples."""
    return {
        "header": f'Details of Credit Agreement with "{subscriber}" for Account Number: {account_no}',
        "tableName": "Consumer24MonthlyPayment",
        "displayText": "Consumer 24 Monthly Payment",
        "dateAccountOpened": date_account_opened,
        "subscriberName": subscriber,
        "accountNo": account_no,
        "subAccountNo": "",
        "currency": "GHS",
        "currentBalanceDebitInd": "D",
        "repaymentFrequency": "Monthly",
        "dateAccountOpened1": None,
        "indicatorDescription": indicator_description,
        "openingBalanceAmt": opening_balance,
        "currentBalanceAmt": current_balance,
        "instalmentAmount": instalment,
        "amountOverdue": amount_overdue,
        "closedDate": closed_date,
        "lastUpdatedDate": last_updated,
        "company": "Company",
        "mH24": "2016 JUL",
        "m24": "#",
        "mH23": "2016 AUG",
        "m23": "#",
        "mH22": "2016 SEP",
        "m22": "#",
        "mH21": "2016 OCT",
        "m21": "#",
        "mH20": "2016 NOV",
        "m20": "#",
        "mH19": "2016 DEC",
        "m19": "#",
        "mH18": "2017 JAN",
        "m18": "#",
        "mH17": "2017 FEB",
        "m17": "#",
        "mH16": "2017 MAR",
        "m16": "#",
        "mH15": "2017 APR",
        "m15": "#",
        "mH14": "2017 MAY",
        "m14": "#",
        "mH13": "2017 JUN",
        "m13": "#",
        "mH12": "2017 JUL",
        "m12": "#",
        "mH11": "2017 AUG",
        "m11": "#",
        "mH10": "2017 SEP",
        "m10": "#",
        "mH09": "2017 OCT",
        "m09": "#",
        "mH08": "2017 NOV",
        "m08": "#",
        "mH07": "2017 DEC",
        "m07": "#",
        "mH06": "2018 JAN",
        "m06": "#",
        "mH05": "2018 FEB",
        "m05": "#",
        "mH04": "2018 MAR",
        "m04": "#",
        "mH03": "2018 APR",
        "m03": "#",
        "mH02": "2018 MAY",
        "m02": "#",
        "mH01": "2018 JUN",
        "m01": "0",
    }


def _credit_agreement_row(
    *,
    date_opened: str,
    subscriber: str,
    account_no: str,
    opening_balance: str,
    current_balance: str,
    instalment: str,
    amount_overdue: str,
    account_status: str,
    months_arrears: str,
    closed_date: str,
    changed_on: str,
    indicator_description: str = "Personal cash loan",
) -> dict:
    return {
        "dateAccountOpened": date_opened,
        "subscriberName": subscriber,
        "accountNo": account_no,
        "subAccountNo": "",
        "indicatorDescription": indicator_description,
        "openingBalanceAmt": opening_balance,
        "currency": "GHS",
        "currentBalanceDebitInd": "D",
        "currentBalanceAmt": current_balance,
        "instalmentAmount": instalment,
        "amountOverdue": amount_overdue,
        "accountStatusCode": account_status,
        "monthsInArrears": months_arrears,
        "closedDate": closed_date,
        "changedOnDate": changed_on,
    }


def _personal_details(
    *,
    consumer_id: int,
    surname: str,
    first_name: str,
    other_names: str,
    birth_date: str,
    nationality: str,
    residential_1: str,
    postal_1: str,
    employer: str,
    gender: str,
    dependants: str,
    national_id: str,
) -> dict:
    search = f"{surname}, {first_name}, {other_names}, {postal_1}"
    header = f"PERSONAL DETAILS SUMMARY: {surname} {first_name} {other_names}"
    return {
        "header": header,
        "consumerID": consumer_id,
        "referenceNo": "",
        "nationality": nationality,
        "nationalIDNo": national_id,
        "passportNo": "",
        "driversLicenseNo": "",
        "pencomIDNo": "",
        "otheridNo": "",
        "birthDate": birth_date,
        "dependants": dependants,
        "gender": gender,
        "maritalStatus": "",
        "residentialAddress1": residential_1,
        "residentialAddress2": "",
        "residentialAddress3": "",
        "residentialAddress4": "",
        "postalAddress1": postal_1,
        "postalAddress2": "",
        "postalAddress3": "",
        "postalAddress4": "",
        "homeTelephoneNo": "",
        "workTelephoneNo": "",
        "cellularNo": "",
        "emailAddress": "",
        "employerDetail": employer,
        "propertyOwnedType": "",
        "surname": surname,
        "firstName": first_name,
        "otherNames": other_names,
        "title": "",
    }


def _credit_account_summary_template(
    *,
    total_accounts_ghs: str,
    active_ghs: str,
    monthly_inst: str,
    outstanding_ghs: str,
    in_arrear_accounts: str,
    amount_arrear_ghs: str,
    good_condition: str,
    rating: str,
) -> dict:
    z = "0"
    zd = "0.00"
    dash = "-"
    return {
        "totalNumberofAccountsGHS": total_accounts_ghs,
        "totalNumberofAccountsUSD": z,
        "totalNumberofAccountsGBP": z,
        "totalNumberofAccountsEUR": z,
        "totalActiveAccountsGHS": active_ghs,
        "totalActiveAccountsUSD": z,
        "totalActiveAccountsGBP": z,
        "totalActiveAccountsEUR": z,
        "totalClosedAccountsGHS": z,
        "totalClosedAccountsUSD": z,
        "totalClosedAccountsGBP": z,
        "totalClosedAccountsEUR": z,
        "totalMonthlyInstalmentGHS": monthly_inst,
        "totalMonthlyInstalmentGBP": zd,
        "totalMonthlyInstalmentUSD": zd,
        "totalMonthlyInstalmentEUR": zd,
        "totalOutstandingdebtGHS": outstanding_ghs,
        "totalOutstandingdebtUSD": zd,
        "totalOutstandingdebtGBP": zd,
        "totalOutstandingdebtEUR": zd,
        "totalAccountInArrearGHS": in_arrear_accounts,
        "totalAccountInArrearUSD": z,
        "totalAccountInArrearGBP": z,
        "totalAccountInArrearEUR": z,
        "totalAmountInArrearGHS": amount_arrear_ghs,
        "totalAmountInArrearUSD": zd,
        "totalAmountInArrearEUR": zd,
        "totalAmountInArrearGBP": zd,
        "totalaccountinGoodconditionGHS": good_condition,
        "totalaccountinGoodconditionUSD": z,
        "totalaccountinGoodconditionGBP": z,
        "totalaccountinGoodconditionEUR": z,
        "totalNumberofJudgementGHS": z,
        "totalNumberofJudgementUSD": z,
        "totalNumberofJudgementGBP": z,
        "totalNumberofJudgementEUR": z,
        "totalJudgementAmountGHS": zd,
        "totalJudgementAmountUSD": zd,
        "totalJudgementAmountGBP": zd,
        "totalJudgementAmountEUR": zd,
        "lastJudgementDateGHS": dash,
        "lastJudgementDateUSD": dash,
        "lastJudgementDateGBP": dash,
        "lastJudgementDateEUR": dash,
        "totalNumberofDishonouredGHS": z,
        "totalNumberofDishonouredUSD": z,
        "totalNumberofDishonouredGBP": z,
        "totalNumberofDishonouredEUR": z,
        "totalDishonouredAmountGHS": zd,
        "totalDishonouredAmountUSD": zd,
        "totalDishonouredAmountGBP": zd,
        "totalDishonouredAmountEUR": zd,
        "lastBouncedChequesDateGHS": dash,
        "lastBouncedChequesDateUSD": dash,
        "lastBouncedChequesDateGBP": dash,
        "lastBouncedChequesDateEUR": dash,
        "rating": rating,
    }


def _account_rating_zeros() -> dict:
    z = "0"
    return {
        "noOfHomeLoanAccountsGood": z,
        "noOfHomeLoanAccountsBad": z,
        "noOfAutoLoanccountsGood": z,
        "noOfAutoLoanAccountsBad": z,
        "noOfStudyLoanAccountsGood": z,
        "noOfStudyLoanAccountsBad": z,
        "noOfPersonalLoanAccountsGood": z,
        "noOfPersonalLoanAccountsBad": z,
        "noOfCreditCardAccountsGood": z,
        "noOfCreditCardAccountsBad": z,
        "noOfRetailAccountsGood": z,
        "noOfRetailAccountsBad": z,
        "noOfJointLoanAccountsGood": z,
        "noOfJointLoanAccountsBad": z,
        "noOfTelecomAccountsGood": z,
        "noOfTelecomAccountsBad": z,
        "noOfOtherAccountsGood": z,
        "noOfOtherAccountsBad": z,
    }


def generate_xds_training_record(i: int) -> dict:
    """
    One row for JSON training upload: only ``consumer_full_report_45``, matching raw XDS
    (no ``applicant_context``).
    """
    subscribers = (
        "UNIBANK",
        "GCB BANK LIMITED",
        "ABSA BANK GHANA LTD",
        "CAL BANK PLC",
        "FIDELITY BANK GHANA",
        "STANBIC BANK GHANA",
        "ZENITH BANK GHANA",
        "ECOBANK GHANA",
        "ACCESS BANK GHANA",
        "UBA GHANA LTD",
    )
    surnames = (
        "NCHAJI",
        "MENSAH",
        "OWUSU",
        "ASANTE",
        "BOATENG",
        "OSEI",
        "AMOAH",
        "APPIAH",
        "DARKO",
        "ADJEI",
    )
    first_names = (
        "JOHN",
        "KWAME",
        "AMA",
        "KOFI",
        "AKOSUA",
        "YAW",
        "EFUA",
        "KOJO",
        "ABENA",
        "KWAKU",
    )
    other_names = (
        "BAAGMA",
        "KWEKU",
        "ADWOA",
        "YAW",
        "AFUA",
        "PETER",
        "MARY",
        "JOSEPH",
        "GRACE",
        "SAMUEL",
    )
    occupations = (
        "POLICE RECRUIT",
        "TEACHER",
        "NURSE",
        "ENGINEER",
        "TRADER",
        "CIVIL SERVANT",
        "DRIVER",
        "ACCOUNTANT",
        "FARMER",
        "CLERK",
    )
    residential = (
        "HSN:C-O NAT POLICE TRAINING SCH",
        "12 LIBERATION ROAD ACCRA",
        "PLOT 45 OSU RE",
        "KANESHIE MARKET AREA",
        "TEMA COMM 9 BLK 4",
        "EAST LEGON STR 7",
        "SPINTEX ROAD NEAR LASHIBI",
        "ADABRAKA MAIN ST",
        "NUNGUA COASTAL RD",
        "DANSOMAN SSNIT FLATS",
    )
    postal = (
        "P O BOX GP 740 ACCRA",
        "P O BOX 1234 ACCRA",
        "P O BOX 567 KUMASI",
        "P O BOX 89 TEMA",
        "P O BOX 2000 ACCRA",
        "P O BOX 44 CAPE COAST",
        "P O BOX 901 TAKORADI",
        "P O BOX 33 SUNYANI",
        "P O BOX 77 HO",
        "P O BOX 12 TAMALE",
    )

    subscriber = subscribers[i % len(subscribers)]
    surname = surnames[i % len(surnames)]
    first_name = first_names[i % len(first_names)]
    other_name = other_names[(i * 3) % len(other_names)]
    res = residential[i % len(residential)]
    post = postal[(i * 5) % len(postal)]
    occupation = occupations[i % len(occupations)]

    uid = 2_580_957 + i * 10_247
    ref = str(uid)
    search_output = f"{surname}, {first_name}, {other_name}, {post}"

    day = 10 + (i % 18)
    month = 1 + (i % 12)
    birth_year = 1978 + (i % 28)
    birth_date = f"{day:02d}/{month:02d}/{birth_year}"

    opened_d, opened_m, opened_y = 15 + (i % 10), 1 + (i % 9), 2015 + (i % 6)
    date_opened = f"{opened_d:02d}/{opened_m:02d}/{opened_y}"
    closed_d, closed_m, closed_y = 10 + (i % 15), 1 + (i % 11), opened_y + 3
    closed_date = f"{closed_d:02d}/{closed_m:02d}/{closed_y}"
    changed_on = f"{(5 + i % 20):02d}/{(1 + i % 8):02d}/{opened_y + 1}"

    opening_k = 5_000 + (i * 1_137) % 80_000
    current_k = int(opening_k * 0.72)
    instalment = 200 + (i * 37) % 900
    opening_balance = f"{opening_k:,}.00"
    current_balance = f"{current_k:,}.00"
    instalment_s = f"{instalment}.00"
    account_no = f"AA{17083 + i * 91:05d}GHRWW"
    employer_detail = (
        "GHANA POLICE SERVICE" if i % 2 == 0 else f"PRIVATE SECTOR EMPLOYER {i % 50}"
    )

    months_arrears = str((i * 2) % 7)
    acct_status = "A" if i % 4 != 0 else "S"
    enquiry_id = str(46_262_833 + i * 1_009)
    date_req = f"{20 + (i % 8):02d}/02/2026 18:0{i % 10}:10"

    inner = {
        "response": {"message": "Success", "statusCode": 200},
        "subjectList": [
            {
                "uniqueID": uid,
                "searchOutput": search_output,
                "reference": ref,
            }
        ],
        "personalDetailsSummary": _personal_details(
            consumer_id=uid,
            surname=surname,
            first_name=first_name,
            other_names=other_name,
            birth_date=birth_date,
            nationality="GHANAIAN",
            residential_1=res,
            postal_1=post,
            employer=employer_detail,
            gender="Male" if i % 2 == 0 else "Female",
            dependants=str(i % 4),
            national_id="" if i % 3 else f"GHA-{uid % 100000000:08d}-{(i % 9) + 1}",
        ),
        "highestDelinquencyRating": {"highestDelinquencyRating": str(i % 4)},
        "creditAccountSummary": _credit_account_summary_template(
            total_accounts_ghs="1",
            active_ghs="1",
            monthly_inst=instalment_s,
            outstanding_ghs=current_balance,
            in_arrear_accounts="1" if int(months_arrears) > 0 else "0",
            amount_arrear_ghs=f"{int(instalment) * int(months_arrears)}.00"
            if int(months_arrears) > 0
            else "0.00",
            good_condition="1",
            rating=str(i % 3),
        ),
        "accountRating": _account_rating_zeros(),
        "creditAgreementSummary": [
            _credit_agreement_row(
                date_opened=date_opened,
                subscriber=subscriber,
                account_no=account_no,
                opening_balance=opening_balance,
                current_balance=current_balance,
                instalment=instalment_s,
                amount_overdue="0.00" if acct_status == "A" else f"{float(instalment_s) * 0.5:.2f}",
                account_status=acct_status,
                months_arrears=months_arrears,
                closed_date=closed_date,
                changed_on=changed_on,
            )
        ],
        "accountMonthlyPaymentHistory": [
            _monthly_payment_history_row(
                account_no=account_no,
                subscriber=subscriber,
                date_account_opened=date_opened,
                closed_date=closed_date,
                last_updated=changed_on,
                indicator_description="Personal cash loan",
                opening_balance=opening_balance,
                current_balance=current_balance,
                instalment=instalment_s,
                amount_overdue="0.00",
            )
        ],
        "adverseDetails": [],
        "defaults": [],
        "judgementSummary": [],
        "jointLoanAccountDetails": [],
        "dudCheqEventSummary": [],
        "telephoneHistory": [],
        "identificationHistory": [],
        "addressHistory": [
            {
                "upDateDate": changed_on,
                "upDateOnDate": changed_on,
                "address1": res,
                "address2": "",
                "address3": "",
                "address4": "",
                "addressTypeInd": "Residential",
            },
            {
                "upDateDate": changed_on,
                "upDateOnDate": changed_on,
                "address1": post,
                "address2": "",
                "address3": "",
                "address4": "",
                "addressTypeInd": "Postal",
            },
        ],
        "employmentHistory": [
            {
                "upDateDate": changed_on,
                "upDateOnDate": changed_on,
                "employerDetail": employer_detail,
                "occupation": occupation,
            }
        ],
        "nameHistory": [
            {
                "lastUpdatedDate": f"{15 + (i % 10):02d}/06/2019",
                "titleCode": "",
                "firstName": first_name,
                "otherNames": other_name,
                "surName": surname,
                "birthDate": birth_date,
            }
        ],
        "guarantorCount": {"guarantorsSecured": "0", "accounts": "0"},
        "guarantorDetails": [],
        "enquiryDetails": {"subscriberEnquiryResultID": enquiry_id, "productID": "45"},
        "enquiryHistory": [
            {
                "subscriberEnquiryResultID": enquiry_id,
                "dateRequested": date_req,
                "subscriberName": "PAYSWITCH COMPANY LIMITED",
                "enquiryReason": "1",
            }
        ],
    }

    return {"consumer_full_report_45": inner}


def generate_xds_training_records(num_records: int) -> list:
    """List of dicts for JSON array upload and ``pd.json_normalize``."""
    return [generate_xds_training_record(i) for i in range(num_records)]


def get_environment() -> str:
    """Determine environment (local or azure)"""
    env = os.getenv("ENVIRONMENT", "local").lower()
    if env not in ["local", "azure"]:
        env = "local"
    return env


def main():
    """Main function to create and upload test file"""
    print("=" * 60)
    print("Script 1: Create and Upload Test JSON File")
    print("=" * 60)
    
    # Load environment variables
    if HAS_DOTENV:
        env_path = os.path.join(TRAINING_INGESTION_ROOT, ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path)
    
    # Determine environment
    env = get_environment()
    print(f"Environment: {env}")
    
    # Configuration
    KEY_VAULT_URL = os.getenv("KEY_VAULT_URL")
    if not KEY_VAULT_URL:
        raise ValueError("KEY_VAULT_URL environment variable is required")
    
    BLOB_STORAGE_ACCOUNT_NAME = os.getenv("BLOB_STORAGE_ACCOUNT_NAME")
    BLOB_CONTAINER_NAME = os.getenv("BLOB_CONTAINER_NAME", "data")
    
    # Initialize Key Vault reader
    try:
        kv_reader = KeyVaultReader(key_vault_url=KEY_VAULT_URL)
    except Exception as e:
        print(f"❌ ERROR: Failed to initialize Key Vault reader: {str(e)}")
        sys.exit(1)
    
    # Get blob storage account name
    if not BLOB_STORAGE_ACCOUNT_NAME:
        try:
            BLOB_STORAGE_ACCOUNT_NAME = kv_reader.get_secret("BlobStorageAccountName")
        except KeyVaultError:
            raise ValueError("BLOB_STORAGE_ACCOUNT_NAME must be set in env or Key Vault")
    
    # Get blob connection string
    blob_connection_string = os.getenv("BLOB_STORAGE_CONNECTION_STRING")
    if not blob_connection_string:
        try:
            for secret_name in ["BlobStorageConnectionString", "StorageAccountConnectionString", "AzureWebJobsStorage"]:
                try:
                    blob_connection_string = kv_reader.get_secret(secret_name)
                    print(f"✅ Retrieved blob storage connection string from Key Vault: {secret_name}")
                    break
                except KeyVaultError:
                    continue
        except Exception as e:
            print(f"⚠️  Could not retrieve blob connection string from Key Vault: {str(e)}")
    
    if not blob_connection_string:
        raise ValueError("BLOB_STORAGE_CONNECTION_STRING must be set in env or Key Vault")
    
    num_records = int(os.getenv("XDS_TEST_NUM_RECORDS", "10"))
    if num_records < 1:
        num_records = 10

    # Generate XDS-shaped JSON rows (see module docstring)
    print(f"\n📝 Generating XDS-shaped training JSON ({num_records} records)...")
    test_records = generate_xds_training_records(num_records)
    
    # Ask for existing data_source_id to satisfy FK to data_sources
    print("\n📋 Enter an existing data_source_id from the data_sources table")
    print("   (run: SELECT id, name FROM data_sources; and pick one)")
    data_source_id = input("   Data Source ID (UUID): ").strip()
    if not data_source_id:
        print("   ❌ data_source_id is required and must already exist in data_sources.")
        sys.exit(1)
    
    file_name = "test_ingestion_1.json"
    raw_file_path = f"{data_source_id}/{file_name}"
    
    # Convert to JSON
    json_content = json.dumps(test_records, indent=2)
    json_bytes = json_content.encode('utf-8')
    file_size_bytes = len(json_bytes)
    
    print(f"✅ Generated test data")
    print(f"   Data Source ID: {data_source_id}")
    print(f"   File Name: {file_name}")
    print(f"   Raw File Path: {raw_file_path}")
    print(f"   File Size: {file_size_bytes} bytes")
    print(f"   Number of Records: {len(test_records)}")
    
    # Upload to blob storage
    print(f"\n📤 Uploading to blob storage...")
    print(f"   Account: {BLOB_STORAGE_ACCOUNT_NAME}")
    print(f"   Container: {BLOB_CONTAINER_NAME}")
    print(f"   Blob Path: {raw_file_path}")
    
    try:
        # Create blob service client
        if blob_connection_string:
            blob_service_client = BlobServiceClient.from_connection_string(blob_connection_string)
        else:
            credential = AzureCliCredential() if env == "local" else DefaultAzureCredential()
            account_url = f"https://{BLOB_STORAGE_ACCOUNT_NAME}.blob.core.windows.net"
            blob_service_client = BlobServiceClient(account_url=account_url, credential=credential)
        
        # Get container client
        container_client = blob_service_client.get_container_client(BLOB_CONTAINER_NAME)
        
        # Ensure container exists
        if not container_client.exists():
            print(f"   Creating container '{BLOB_CONTAINER_NAME}'...")
            container_client.create_container()
        
        # Upload blob
        blob_client = container_client.get_blob_client(raw_file_path)
        blob_client.upload_blob(json_bytes, overwrite=True)
        
        blob_url = blob_client.url
        print(f"✅ File uploaded successfully!")
        print(f"   Blob URL: {blob_url}")
        
    except Exception as e:
        print(f"❌ ERROR: Failed to upload file: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # Print summary for next scripts
    print("\n" + "=" * 60)
    print("✅ Script 1 Complete - Summary")
    print("=" * 60)
    print("Use these values in Script 2 (insert_training_upload_record.py):")
    print(f"  DATA_SOURCE_ID = {data_source_id}")
    print(f"  FILE_NAME = {file_name}")
    print(f"  RAW_FILE_PATH = {raw_file_path}")
    print(f"  FILE_SIZE_BYTES = {file_size_bytes}")
    print(f"  FILE_FORMAT = json")
    print(f"  RECORD_COUNT = {len(test_records)}")
    print("\n💡 Tip: Save these values or run Script 2 immediately after this one.")
    print("=" * 60)


if __name__ == "__main__":
    main()
