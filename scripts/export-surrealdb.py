#!/usr/bin/env python3
"""
SurrealDB Logical Export Script
Exports SurrealDB data via HTTP API to GCS

Usage:
    python export-surrealdb.py --namespace partyscene --database partyscene
"""

import argparse
import json
import sys
from datetime import datetime
from typing import Any, Dict, List

import requests


def export_table(
    base_url: str,
    namespace: str,
    database: str,
    table: str,
    username: str,
    password: str,
) -> List[Dict[str, Any]]:
    """Export all records from a specific table."""
    query = f"SELECT * FROM {table};"
    
    headers = {
        "NS": namespace,
        "DB": database,
        "Accept": "application/json",
    }
    
    # Try with auth if username/password provided
    if username and password:
        # SurrealDB HTTP API uses query params for auth
        params = {
            "user": username,
            "pass": password,
        }
    else:
        params = {}
    
    response = requests.post(
        f"{base_url}/sql",
        headers=headers,
        params=params,
        data=query,
        timeout=300,
    )
    
    if response.status_code != 200:
        print(f"Error exporting table {table}: {response.status_code} - {response.text}")
        return []
    
    result = response.json()
    if result and "result" in result and len(result["result"]) > 0:
        return result["result"][0].get("result", [])
    return []


def get_all_tables(
    base_url: str,
    namespace: str,
    database: str,
    username: str,
    password: str,
) -> List[str]:
    """Get list of all tables in the database."""
    query = "INFO FOR DB;"
    
    headers = {
        "NS": namespace,
        "DB": database,
        "Accept": "application/json",
    }
    
    if username and password:
        params = {
            "user": username,
            "pass": password,
        }
    else:
        params = {}
    
    response = requests.post(
        f"{base_url}/sql",
        headers=headers,
        params=params,
        data=query,
        timeout=30,
    )
    
    if response.status_code != 200:
        print(f"Error getting tables: {response.status_code} - {response.text}")
        return []
    
    result = response.json()
    if result and "result" in result and len(result["result"]) > 0:
        db_info = result["result"][0].get("result", {})
        return db_info.get("tables", [])
    return []


def export_schema(
    base_url: str,
    namespace: str,
    database: str,
    username: str,
    password: str,
) -> str:
    """Export database schema (tables, fields, indexes)."""
    tables = get_all_tables(base_url, namespace, database, username, password)
    
    schema_lines = [
        f"-- SurrealDB Schema Export",
        f"-- Namespace: {namespace}",
        f"-- Database: {database}",
        f"-- Exported: {datetime.utcnow().isoformat()}",
        "",
        "USE NS partyscene;",
        "USE DB partyscene;",
        "",
    ]
    
    for table in tables:
        schema_lines.append(f"-- Table: {table}")
        # Get table info
        query = f"INFO FOR TABLE {table};"
        
        headers = {
            "NS": namespace,
            "DB": database,
            "Accept": "application/json",
        }
        
        if username and password:
            params = {"user": username, "pass": password}
        else:
            params = {}
        
        response = requests.post(
            f"{base_url}/sql",
            headers=headers,
            params=params,
            data=query,
            timeout=30,
        )
        
        if response.status_code == 200:
            result = response.json()
            if result and "result" in result and len(result["result"]) > 0:
                table_info = result["result"][0].get("result", {})
                fields = table_info.get("fields", {})
                for field_name, field_info in fields.items():
                    schema_lines.append(f"-- {field_name}: {field_info}")
        
        schema_lines.append("")
    
    return "\n".join(schema_lines)


def export_data(
    base_url: str,
    namespace: str,
    database: str,
    username: str,
    password: str,
    tables_to_exclude: List[str] = None,
) -> str:
    """Export all data from the database as SurrealQL."""
    tables = get_all_tables(base_url, namespace, database, username, password)
    
    if tables_to_exclude:
        tables = [t for t in tables if t not in tables_to_exclude]
    
    export_lines = [
        f"-- SurrealDB Data Export",
        f"-- Namespace: {namespace}",
        f"-- Database: {database}",
        f"-- Exported: {datetime.utcnow().isoformat()}",
        "",
        "USE NS partyscene;",
        "USE DB partyscene;",
        "",
    ]
    
    for table in tables:
        print(f"Exporting table: {table}")
        records = export_table(base_url, namespace, database, table, username, password)
        
        if records:
            export_lines.append(f"-- Table: {table} ({len(records)} records)")
            for record in records:
                # Convert to SurrealQL INSERT statement
                record_id = record.get("id")
                if record_id:
                    # Remove id from the record dict for the UPDATE
                    record_copy = {k: v for k, v in record.items() if k != "id"}
                    if record_copy:
                        # Use UPDATE with id
                        export_lines.append(f"UPDATE {record_id} SET {json.dumps(record_copy)};")
                    else:
                        # Empty record, just create it
                        export_lines.append(f"CREATE {record_id};")
            export_lines.append("")
    
    return "\n".join(export_lines)


def main():
    parser = argparse.ArgumentParser(description="Export SurrealDB data to SurrealQL")
    parser.add_argument(
        "--endpoint",
        default="http://localhost:8000",
        help="SurrealDB endpoint URL",
    )
    parser.add_argument(
        "--namespace",
        default="partyscene",
        help="SurrealDB namespace",
    )
    parser.add_argument(
        "--database",
        default="partyscene",
        help="SurrealDB database",
    )
    parser.add_argument(
        "--username",
        default="root",
        help="SurrealDB username",
    )
    parser.add_argument(
        "--password",
        default="root",
        help="SurrealDB password",
    )
    parser.add_argument(
        "--output",
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--exclude-tables",
        nargs="*",
        help="Tables to exclude from export",
    )
    
    args = parser.parse_args()
    
    # Export schema
    print("Exporting schema...")
    schema = export_schema(
        args.endpoint,
        args.namespace,
        args.database,
        args.username,
        args.password,
    )
    
    # Export data
    print("Exporting data...")
    data = export_data(
        args.endpoint,
        args.namespace,
        args.database,
        args.username,
        args.password,
        args.exclude_tables,
    )
    
    full_export = schema + "\n" + data
    
    if args.output:
        with open(args.output, "w") as f:
            f.write(full_export)
        print(f"Export written to {args.output}")
    else:
        print(full_export)


if __name__ == "__main__":
    main()
