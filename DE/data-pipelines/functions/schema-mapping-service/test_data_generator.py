"""
Test Data Generator
Creates test datasets with PII columns in multiple formats for ADLS testing
"""

import json
import csv
import pandas as pd
from pathlib import Path
from datetime import datetime
import random

# Ghanaian names and data
GHANAIAN_FIRST_NAMES = [
    "Kwame", "Ama", "Kofi", "Akosua", "Yaw", "Efua", "Kojo", "Abena",
    "Kwaku", "Adwoa", "Fiifi", "Aba", "Kweku", "Akua", "Yaa", "Esi",
    "Kobina", "Afi", "Kwabena", "Ama", "Kofi", "Akosua", "Yaw", "Efua"
]

GHANAIAN_LAST_NAMES = [
    "Mensah", "Owusu", "Asante", "Boateng", "Osei", "Amoah", "Appiah",
    "Darko", "Adjei", "Agyeman", "Bonsu", "Danso", "Frimpong", "Gyasi",
    "Kwarteng", "Nkrumah", "Ofori", "Sarpong", "Tetteh", "Yeboah"
]

GHANAIAN_EMAIL_DOMAINS = [
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "ghana.com", "mtn.com.gh", "vodafone.com.gh"
]

GHANAIAN_CITIES = [
    "Accra", "Kumasi", "Tamale", "Takoradi", "Sunyani", "Cape Coast",
    "Koforidua", "Ho", "Bolgatanga", "Wa", "Techiman", "Tema"
]

GHANAIAN_STREETS = [
    "Ring Road", "Oxford Street", "Independence Avenue", "Liberation Road",
    "Airport Road", "Spintex Road", "Tetteh Quarshie Avenue", "Cantonments Road"
]


def generate_ghanaian_phone():
    """Generate realistic Ghanaian phone number"""
    prefixes = ["020", "024", "026", "027", "050", "054", "055", "056", "057"]
    prefix = random.choice(prefixes)
    number = f"+233{prefix[1:]}{random.randint(1000000, 9999999)}"
    return number


def generate_ghanaian_email(first_name, last_name):
    """Generate email from name"""
    formats = [
        f"{first_name.lower()}.{last_name.lower()}",
        f"{first_name.lower()}{last_name.lower()}",
        f"{first_name.lower()}{random.randint(1, 999)}",
        f"{last_name.lower()}{random.randint(1, 999)}"
    ]
    username = random.choice(formats)
    domain = random.choice(GHANAIAN_EMAIL_DOMAINS)
    return f"{username}@{domain}"


def generate_national_id():
    """Generate Ghanaian National ID format (GHA-XXXXXXXX-X)"""
    return f"GHA-{random.randint(10000000, 99999999)}-{random.randint(1, 9)}"


def generate_passport_number():
    """Generate passport number format"""
    return f"G{random.randint(100000, 999999)}"


def generate_address(city):
    """Generate address"""
    street_num = random.randint(1, 999)
    street = random.choice(GHANAIAN_STREETS)
    return f"{street_num} {street}, {city}"


def generate_test_data(num_rows=500):
    """Generate test data with PII columns"""
    data = []
    
    for i in range(num_rows):
        first_name = random.choice(GHANAIAN_FIRST_NAMES)
        last_name = random.choice(GHANAIAN_LAST_NAMES)
        city = random.choice(GHANAIAN_CITIES)
        
        record = {
            # PII Columns
            "customer_name": f"{first_name} {last_name}",
            "first_name": first_name,
            "last_name": last_name,
            "email_address": generate_ghanaian_email(first_name, last_name),
            "contact_email": generate_ghanaian_email(first_name, last_name),
            "phone_number": generate_ghanaian_phone(),
            "mobile_number": generate_ghanaian_phone(),
            "national_id": generate_national_id(),
            "passport_number": generate_passport_number(),
            "home_address": generate_address(city),
            "billing_address": generate_address(city),
            "city": city,
            "postal_code": f"GA{random.randint(100, 999)}",
            
            # Non-PII Columns (credit scoring related)
            "age": random.randint(18, 80),
            "monthly_income": round(random.uniform(1000, 50000), 2),
            "loan_amount": round(random.uniform(5000, 100000), 2),
            "loan_tenure_months": random.choice([12, 18, 24, 36, 48, 60]),
            "employment_years": round(random.uniform(0.5, 30), 1),
            "employment_type": random.choice(["Salaried", "Self-Employed", "Government"]),
            "account_balance": round(random.uniform(1000, 200000), 2),
            "savings_balance": round(random.uniform(500, 150000), 2),
            "existing_loans_balance": round(random.uniform(0, 100000), 2),
            "monthly_loan_repayment": round(random.uniform(0, 5000), 2),
            "account_age_months": random.randint(1, 240),
            "monthly_transactions_count": random.randint(5, 200),
            "credit_history_months": random.randint(0, 240),
            "num_credit_inquiries": random.randint(0, 10),
            "num_late_payments": random.randint(0, 12),
            "approved": random.choice([0, 1])
        }
        data.append(record)
    
    return data


def create_csv_file(data, output_path):
    """Create CSV file"""
    df = pd.DataFrame(data)
    df.to_csv(output_path, index=False)
    print(f"Created CSV: {output_path} ({len(data)} rows)")


def create_json_file(data, output_path):
    """Create JSON file (array of objects)"""
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Created JSON: {output_path} ({len(data)} rows)")


def create_jsonl_file(data, output_path):
    """Create JSONL file (newline-delimited JSON)"""
    with open(output_path, 'w', encoding='utf-8') as f:
        for record in data:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
    print(f"Created JSONL: {output_path} ({len(data)} rows)")


def create_parquet_file(data, output_path):
    """Create Parquet file"""
    df = pd.DataFrame(data)
    df.to_parquet(output_path, index=False, engine='pyarrow')
    print(f"Created Parquet: {output_path} ({len(data)} rows)")


def create_excel_file(data, output_path):
    """Create Excel file"""
    df = pd.DataFrame(data)
    df.to_excel(output_path, index=False, engine='openpyxl')
    print(f"Created Excel: {output_path} ({len(data)} rows)")


def create_tsv_file(data, output_path):
    """Create TSV file"""
    df = pd.DataFrame(data)
    df.to_csv(output_path, index=False, sep='\t')
    print(f"Created TSV: {output_path} ({len(data)} rows)")


def main():
    """Generate all test data files"""
    output_dir = Path(__file__).parent / "test_data"
    output_dir.mkdir(exist_ok=True)
    
    print("=" * 60)
    print("Generating Test Data with PII Columns")
    print("=" * 60)
    
    # Generate data (500 rows - large dataset)
    print("\nGenerating 500 rows of test data...")
    data = generate_test_data(num_rows=500)
    
    # Create files in all formats
    base_name = "test_data_with_pii"
    
    print(f"\nCreating files in {output_dir}...")
    create_csv_file(data, output_dir / f"{base_name}.csv")
    create_json_file(data, output_dir / f"{base_name}.json")
    create_jsonl_file(data, output_dir / f"{base_name}.jsonl")
    create_parquet_file(data, output_dir / f"{base_name}.parquet")
    create_excel_file(data, output_dir / f"{base_name}.xlsx")
    create_tsv_file(data, output_dir / f"{base_name}.tsv")
    
    print("\n" + "=" * 60)
    print("Test data generation complete!")
    print(f"Files created in: {output_dir}")
    print("=" * 60)
    
    # Print column summary
    print("\nColumns in test data:")
    print(f"  PII Columns: {len([c for c in data[0].keys() if any(pii in c.lower() for pii in ['name', 'email', 'phone', 'id', 'address', 'city', 'postal'])])}")
    print(f"  Non-PII Columns: {len([c for c in data[0].keys() if not any(pii in c.lower() for pii in ['name', 'email', 'phone', 'id', 'address', 'city', 'postal'])])}")
    print(f"  Total Columns: {len(data[0].keys())}")


if __name__ == "__main__":
    main()
