"""
Test script for filter endpoints and status inheritance.
Run this after starting the API server.
"""

import requests
import json
import time
from datetime import datetime, timedelta

# Configuration
BASE_URL = "http://localhost:8000/api"
HEADERS = {"Content-Type": "application/json"}


def print_section(title):
    """Print a section header"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def get_id(obj):
    """Safely extract ID from object (handles both 'id' and '_id' fields)"""
    return obj.get("id") or obj.get("_id") or "unknown"


def test_create_text_source():
    """Test creating a source from text (should have status='user_input')"""
    print_section("TEST 1: Create Source from Text Upload")

    # Use a unique timestamp to avoid duplicates
    timestamp = datetime.now().isoformat()

    payload = {
        "text": f"This is a test article about illegal fishing involving tuna in the Pacific Ocean. The vessel XYZ-{timestamp} was caught exceeding quotas on {timestamp}. This is unique content to avoid duplicates.",
        "title": f"Test Illegal Fishing Incident {timestamp}",
        "author": "Test Author",
        "publisher": "Test News",
        "source_type": "news",
        "user_id": "test_user",
    }

    response = requests.post(f"{BASE_URL}/incidents", json=payload, headers=HEADERS)
    print(f"Status Code: {response.status_code}")

    if response.status_code == 202:
        task_data = response.json()
        task_id = task_data["task_id"]
        print(f"Task ID: {task_id}")

        # Poll task status
        print("Waiting for task to complete...")

        max_attempts = 30
        for i in range(max_attempts):
            time.sleep(5)
            task_response = requests.get(f"{BASE_URL}/tasks/{task_id}")
            task_status = task_response.json()
            print(
                f"  Attempt {i+1}: Status = {task_status['status']}, Progress = {task_status.get('progress', {})}"
            )

            if task_status["status"] in ["completed", "failed"]:
                if task_status["status"] == "completed":
                    result = task_status.get("result", {})
                    print("\nTask completed!")
                    print(f"Source ID: {result.get('source_id')}")
                    print(f"Incident IDs: {result.get('incident_ids')}")
                    return result.get("source_id"), result.get("incident_ids", [])
                else:
                    print(f"\n Task failed: {task_status.get('error')}")
                    return None, None

        print("\nTask timed out")
        return None, None
    else:
        print(f" Error: {response.text}")
        return None, None


def test_source_filters():
    """Test source filtering endpoints"""
    print_section("TEST 2: Source Filters")

    # Test 1: Filter by input_category
    print("\n--- Filter by input_category=text_upload ---")
    response = requests.get(f"{BASE_URL}/sources?input_category=text_upload&limit=5")
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Total sources found: {data['pagination']['total']}")
        for source in data["sources"][:2]:  # Show first 2
            source_id = get_id(source)
            print(
                f"  - ID: {source_id}, input_category: {source.get('input_category')}, status: {source.get('status')}, source_type: {source.get('source_type')}"
            )
    else:
        print(f"Error: {response.text}")

    # Test 2: Filter by source_type
    print("\n--- Filter by source_type=news ---")
    response = requests.get(f"{BASE_URL}/sources?source_type=news&limit=5")
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Total sources found: {data['pagination']['total']}")
        for source in data["sources"][:2]:
            source_id = get_id(source)
            print(
                f"  - ID: {source_id}, source_type: {source.get('source_type')}, input_category: {source.get('input_category')}"
            )
    else:
        print(f"Error: {response.text}")

    # Test 3: Filter by status
    print("\n--- Filter by status=user_input ---")
    response = requests.get(f"{BASE_URL}/sources?status=user_input&limit=5")
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Total sources found: {data['pagination']['total']}")
        for source in data["sources"][:2]:
            source_id = get_id(source)
            print(
                f"  - ID: {source_id}, status: {source.get('status')}, input_category: {source.get('input_category')}"
            )
    else:
        print(f"Error: {response.text}")

    # Test 4: Filter by article_scope
    print("\n--- Filter by article_scope='Single Incident' ---")
    response = requests.get(f"{BASE_URL}/sources?article_scope=Single Incident&limit=5")
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Total sources found: {data['pagination']['total']}")
        for source in data["sources"][:2]:
            source_id = get_id(source)
            article_scope = source.get("article_scope", {})
            if isinstance(article_scope, dict):
                print(
                    f"  - ID: {source_id}, article_scope: {article_scope.get('articleType')}"
                )
            else:
                print(f"  - ID: {source_id}, article_scope: {article_scope}")
    else:
        print(f"Error: {response.text}")

    # Test 5: Combined filters
    print("\n--- Combined: input_category=text_upload AND source_type=news ---")
    response = requests.get(
        f"{BASE_URL}/sources?input_category=text_upload&source_type=news&limit=5"
    )
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Total sources found: {data['pagination']['total']}")
        for source in data["sources"][:2]:
            source_id = get_id(source)
            print(
                f"  - ID: {source_id}, input_category: {source.get('input_category')}, source_type: {source.get('source_type')}"
            )
    else:
        print(f"Error: {response.text}")


def test_incident_filters():
    """Test incident filtering endpoints"""
    print_section("TEST 3: Incident Filters")

    # Test 1: Filter by status
    print("\n--- Filter by status=user_input ---")
    response = requests.get(f"{BASE_URL}/incidents?status=user_input&limit=5")
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Total incidents found: {data['pagination']['total']}")
        for incident in data["reports"][:2]:
            incident_id = get_id(incident)
            print(f"  - ID: {incident_id}, status: {incident.get('status')}")
    else:
        print(f"Error: {response.text}")

    # Test 2: Filter by input_category (via primary_source)
    print("\n--- Filter by input_category=text_upload ---")
    response = requests.get(f"{BASE_URL}/incidents?input_category=text_upload&limit=5")
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Total incidents found: {data['pagination']['total']}")
        for incident in data["reports"][:2]:
            incident_id = get_id(incident)
            primary_source = incident.get("primary_source", {})
            if isinstance(primary_source, dict):
                print(
                    f"  - ID: {incident_id}, primary_source.input_category: {primary_source.get('input_category')}"
                )
    else:
        print(f"Error: {response.text}")

    # Test 3: Filter by status=extracted
    print("\n--- Filter by status=extracted ---")
    response = requests.get(f"{BASE_URL}/incidents?status=extracted&limit=5")
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Total incidents found: {data['pagination']['total']}")
        for incident in data["reports"][:2]:
            incident_id = get_id(incident)
            print(f"  - ID: {incident_id}, status: {incident.get('status')}")
    else:
        print(f"Error: {response.text}")


def test_date_filters():
    """Test date range filtering"""
    print_section("TEST 4: Date Range Filters")

    # Calculate date ranges
    now = datetime.now()
    one_week_ago = now - timedelta(days=7)
    one_month_ago = now - timedelta(days=30)

    # Test 1: Sources created in last 7 days
    print("\n--- Sources created in last 7 days ---")
    response = requests.get(
        f"{BASE_URL}/sources?created_after={one_week_ago.isoformat()}&limit=5"
    )
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Total sources found: {data['pagination']['total']}")
        for source in data["sources"][:2]:
            source_id = get_id(source)
            created = source.get("created_at", "N/A")
            print(f"  - ID: {source_id}, created_at: {created}")
    else:
        print(f"Error: {response.text}")

    # Test 2: Incidents created in last 30 days
    print("\n--- Incidents created in last 30 days ---")
    response = requests.get(
        f"{BASE_URL}/incidents?created_after={one_month_ago.isoformat()}&limit=5"
    )
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Total incidents found: {data['pagination']['total']}")
        for incident in data["reports"][:2]:
            incident_id = get_id(incident)
            created = incident.get("created_at", "N/A")
            print(f"  - ID: {incident_id}, created_at: {created}")
    else:
        print(f"Error: {response.text}")

    # Test 3: Sources modified in specific date range
    print("\n--- Sources modified between 1 month ago and 1 week ago ---")
    response = requests.get(
        f"{BASE_URL}/sources?modified_after={one_month_ago.isoformat()}&modified_before={one_week_ago.isoformat()}&limit=5"
    )
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Total sources found: {data['pagination']['total']}")
    else:
        print(f"Error: {response.text}")


def test_sort_order():
    """Test sort order functionality"""
    print_section("TEST 5: Sort Order")

    # Test 1: Ascending order
    print("\n--- Sources sorted by created_at ascending ---")
    response = requests.get(
        f"{BASE_URL}/sources?sort_by=created_at&sort_order=asc&limit=3"
    )
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Total sources: {data['pagination']['total']}")
        for source in data["sources"]:
            source_id = get_id(source)
            created = source.get("created_at", "N/A")
            print(f"  - ID: {source_id}, created_at: {created}")
    else:
        print(f" Error: {response.text}")

    # Test 2: Descending order (default)
    print("\n--- Incidents sorted by created_at descending ---")
    response = requests.get(
        f"{BASE_URL}/incidents?sort_by=created_at&sort_order=desc&limit=3"
    )
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Total incidents: {data['pagination']['total']}")
        for incident in data["reports"]:
            incident_id = get_id(incident)
            created = incident.get("created_at", "N/A")
            print(f"  - ID: {incident_id}, created_at: {created}")
    else:
        print(f" Error: {response.text}")


def test_user_filters():
    """Test user filtering"""
    print_section("TEST 6: User Filters")

    # Test 1: Filter by created_by
    print("\n--- Sources created by 'test_user' ---")
    response = requests.get(f"{BASE_URL}/sources?created_by=test_user&limit=5")
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Total sources found: {data['pagination']['total']}")
        for source in data["sources"][:2]:
            source_id = get_id(source)
            created_by = source.get("created_by", "N/A")
            print(f"  - ID: {source_id}, created_by: {created_by}")
    else:
        print(f" Error: {response.text}")

    # Test 2: Filter by created_by for incidents
    print("\n--- Incidents created by 'test_user' ---")
    response = requests.get(f"{BASE_URL}/incidents?created_by=test_user&limit=5")
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Total incidents found: {data['pagination']['total']}")
        for incident in data["reports"][:2]:
            incident_id = get_id(incident)
            created_by = incident.get("created_by", "N/A")
            print(f"  - ID: {incident_id}, created_by: {created_by}")
    else:
        print(f" Error: {response.text}")


def test_event_date_filters():
    """Test event date filtering for incidents"""
    print_section("TEST 7: Event Date Filters")

    # Test 1: Incidents with events in 2024
    print("\n--- Incidents with events in 2024 ---")
    response = requests.get(
        f"{BASE_URL}/incidents?event_date_after=2024-01-01&event_date_before=2024-12-31&limit=5"
    )
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Total incidents found: {data['pagination']['total']}")
        for incident in data["reports"][:2]:
            incident_id = get_id(incident)
            extracted_info = incident.get("extracted_information", {})
            event_data = extracted_info.get("eventData") if extracted_info else None
            if event_data and isinstance(event_data, dict):
                event_date = event_data.get("eventDate", "N/A")
            else:
                event_date = "N/A"
            print(f"  - ID: {incident_id}, event_date: {event_date}")
    else:
        print(f" Error: {response.text}")

    # Test 2: Recent incidents (events after a certain date)
    print("\n--- Incidents with events after 2023-01-01 ---")
    response = requests.get(f"{BASE_URL}/incidents?event_date_after=2023-01-01&limit=5")
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Total incidents found: {data['pagination']['total']}")
    else:
        print(f" Error: {response.text}")


def test_combined_filters():
    """Test combining multiple high-priority filters"""
    print_section("TEST 8: Combined High-Priority Filters")

    # Complex query: user-created sources from last week, sorted ascending
    one_week_ago = (datetime.now() - timedelta(days=7)).isoformat()

    print(
        "\n--- User-created sources from last 7 days, news type, sorted ascending ---"
    )
    response = requests.get(
        f"{BASE_URL}/sources?status=user_input&created_after={one_week_ago}&source_type=news&sort_by=created_at&sort_order=asc&limit=5"
    )
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Total sources found: {data['pagination']['total']}")
        for source in data["sources"][:2]:
            source_id = get_id(source)
            print(
                f"  - ID: {source_id}, status: {source.get('status')}, source_type: {source.get('source_type')}, created: {source.get('created_at', 'N/A')}"
            )
    else:
        print(f" Error: {response.text}")


def test_status_inheritance(source_id, incident_ids):
    """Test that incident inherits status from source"""
    print_section("TEST 9: Status Inheritance")

    if not source_id or not incident_ids:
        print("Skipping - no source/incident created in previous test")
        return

    # Get source
    print(f"\n--- Checking Source {source_id} ---")
    response = requests.get(f"{BASE_URL}/sources/{source_id}")
    if response.status_code == 200:
        source = response.json()
        source_status = source.get("status")
        source_input_category = source.get("input_category")
        source_type = source.get("source_type")
        print(f"Source status: {source_status}")
        print(f"Source input_category: {source_input_category}")
        print(f"Source source_type: {source_type}")

        # Expected values for text upload
        expected_status = "user_input"
        expected_input_category = "text_upload"

        if source_status == expected_status:
            print(f"Source status correct! Expected '{expected_status}'")
        else:
            print(
                f" Source status incorrect! Expected '{expected_status}', got '{source_status}'"
            )

        if source_input_category == expected_input_category:
            print(
                f"Source input_category correct! Expected '{expected_input_category}'"
            )
        else:
            print(
                f" Source input_category incorrect! Expected '{expected_input_category}', got '{source_input_category}'"
            )
    else:
        print(f" Could not fetch source: {response.status_code} - {response.text}")
        return

    # Get incident(s)
    for incident_id in incident_ids:
        print(f"\n--- Checking Incident {incident_id} ---")
        response = requests.get(f"{BASE_URL}/incidents/{incident_id}")
        if response.status_code == 200:
            incident = response.json()
            incident_status = incident.get("status")
            print(f"Incident status: {incident_status}")

            # Check if they match
            if incident_status == source_status:
                print(f"Status inheritance working! Both are '{incident_status}'")
            else:
                print(
                    f" Status mismatch! Source='{source_status}', Incident='{incident_status}'"
                )
        else:
            print(
                f" Could not fetch incident: {response.status_code} - {response.text}"
            )


def main():
    """Run all tests"""
    print("\n" + "-" * 30)
    print("  COMPREHENSIVE FILTER TEST SUITE")
    print("-" * 30)

    try:
        # Test 1: Create a text source (should be status='user_input')
        source_id, incident_ids = test_create_text_source()

        # Test 2: Test source filters
        test_source_filters()

        # Test 3: Test incident filters
        test_incident_filters()

        # Test 4: Date range filters (HIGH PRIORITY)
        test_date_filters()

        # Test 5: Sort order (HIGH PRIORITY)
        test_sort_order()

        # Test 6: User filters (HIGH PRIORITY)
        test_user_filters()

        # Test 7: Event date filters (HIGH PRIORITY)
        test_event_date_filters()

        # Test 8: Combined filters
        test_combined_filters()

        # Test 9: Verify status inheritance
        test_status_inheritance(source_id, incident_ids)

        print_section("ALL TESTS COMPLETED")

    except Exception as e:
        print(f"\n Error during testing: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
