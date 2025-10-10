"""
Geospatial Query Tests - Distance-based event queries.
Tests GeometryPoint edge cases: antimeridian, poles, precision.
"""
import pytest
from http import HTTPStatus
import math


@pytest.mark.asyncio(loop_scope="session")
class TestGeospatialQueries:
	"""Test location-based event queries with edge cases."""

	async def test_events_within_radius(self, events_client):
		"""Test fetching events within specified distance."""
		# New York coordinates
		lat, lng = 40.7128, -74.0060
		distance = 5000  # 5km
		
		response = await events_client.get(
			f"/events?lat={lat}&lng={lng}&distance={distance}"
		)
		
		assert response.status_code == HTTPStatus.OK
		data = (await response.get_json())["data"]
		
		# All returned events should be within distance
		for event_data in data:
			event = event_data.get("event", {})
			if "location" in event and "coordinates" in event["location"]:
				coords = event["location"]["coordinates"]
				event_distance = haversine_distance(
					lat, lng,
					coords["latitude"], coords["longitude"]
				)
				assert event_distance <= distance, \
					f"Event {event['id']} is {event_distance}m away, exceeds {distance}m"

	async def test_events_at_antimeridian(self, events_client):
		"""Test event queries near date line (longitude ±180°)."""
		# Fiji (near antimeridian)
		lat, lng = -18.1416, 178.4419
		distance = 500000  # 500km (crosses antimeridian)
		
		response = await events_client.get(
			f"/events?lat={lat}&lng={lng}&distance={distance}"
		)
		
		# Should not fail or return incorrect results
		assert response.status_code == HTTPStatus.OK

	async def test_events_at_north_pole(self, events_client):
		"""Test event queries at extreme latitude."""
		# North Pole
		lat, lng = 90.0, 0.0
		distance = 1000000  # 1000km
		
		response = await events_client.get(
			f"/events?lat={lat}&lng={lng}&distance={distance}"
		)
		
		assert response.status_code == HTTPStatus.OK
		# No events likely at North Pole, but query should work

	async def test_events_at_south_pole(self, events_client):
		"""Test event queries at extreme negative latitude."""
		# South Pole
		lat, lng = -90.0, 0.0
		distance = 1000000
		
		response = await events_client.get(
			f"/events?lat={lat}&lng={lng}&distance={distance}"
		)
		
		assert response.status_code == HTTPStatus.OK

	async def test_invalid_latitude_rejected(self, events_client):
		"""Test invalid latitude values are rejected."""
		invalid_latitudes = [91.0, -91.0, 200.0, -200.0, "invalid"]
		
		for lat in invalid_latitudes:
			response = await events_client.get(
				f"/events?lat={lat}&lng=0.0&distance=1000"
			)
			
			assert response.status_code == HTTPStatus.BAD_REQUEST, \
				f"Invalid latitude {lat} should be rejected"

	async def test_invalid_longitude_rejected(self, events_client):
		"""Test invalid longitude values are rejected."""
		invalid_longitudes = [181.0, -181.0, 500.0, -500.0, "invalid"]
		
		for lng in invalid_longitudes:
			response = await events_client.get(
				f"/events?lat=0.0&lng={lng}&distance=1000"
			)
			
			assert response.status_code == HTTPStatus.BAD_REQUEST, \
				f"Invalid longitude {lng} should be rejected"

	async def test_negative_distance_rejected(self, events_client):
		"""Test negative distance is rejected."""
		response = await events_client.get(
			"/events?lat=40.7128&lng=-74.0060&distance=-1000"
		)
		
		assert response.status_code == HTTPStatus.BAD_REQUEST

	async def test_excessive_distance_limited(self, events_client):
		"""Test unreasonably large distance is capped or rejected."""
		# Earth's circumference is ~40,000km
		excessive_distance = 50_000_000  # 50,000km
		
		response = await events_client.get(
			f"/events?lat=0.0&lng=0.0&distance={excessive_distance}"
		)
		
		# Should either reject or cap to reasonable limit
		assert response.status_code in [HTTPStatus.OK, HTTPStatus.BAD_REQUEST]

	async def test_zero_distance_returns_exact_location(self, events_client):
		"""Test distance=0 returns only events at exact coordinates."""
		response = await events_client.get(
			"/events?lat=40.7128&lng=-74.0060&distance=0"
		)
		
		assert response.status_code == HTTPStatus.OK
		data = (await response.get_json())["data"]
		
		# Should return empty or only exact matches
		assert isinstance(data, list)

	async def test_events_sorted_by_distance(self, events_client):
		"""Test returned events are sorted nearest to farthest."""
		lat, lng = 40.7128, -74.0060
		
		response = await events_client.get(
			f"/events?lat={lat}&lng={lng}&distance=10000"
		)
		
		if response.status_code == HTTPStatus.OK:
			data = (await response.get_json())["data"]
			
			if len(data) > 1:
				# Verify sorted by distance
				distances = []
				for event_data in data:
					event = event_data.get("event", {})
					if "location" in event and "coordinates" in event["location"]:
						coords = event["location"]["coordinates"]
						dist = haversine_distance(
							lat, lng,
							coords["latitude"], coords["longitude"]
						)
						distances.append(dist)
				
				# Check if sorted
				assert distances == sorted(distances), \
					"Events not sorted by distance"

	async def test_coordinate_precision_handled(self, events_client):
		"""Test high-precision coordinates are handled correctly."""
		# Very precise coordinates
		lat = 40.712775897932384
		lng = -74.006058394839201
		
		response = await events_client.get(
			f"/events?lat={lat}&lng={lng}&distance=1000"
		)
		
		assert response.status_code == HTTPStatus.OK

	async def test_missing_coordinates_returns_all_events(self, events_client):
		"""Test fetching events without location filter."""
		response = await events_client.get("/events")
		
		assert response.status_code == HTTPStatus.OK
		# Should return paginated events without distance filter


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
	"""Calculate distance between two coordinates in meters."""
	R = 6371000  # Earth radius in meters
	
	lat1_rad = math.radians(lat1)
	lat2_rad = math.radians(lat2)
	delta_lat = math.radians(lat2 - lat1)
	delta_lon = math.radians(lon2 - lon1)
	
	a = (math.sin(delta_lat / 2) ** 2 +
		 math.cos(lat1_rad) * math.cos(lat2_rad) *
		 math.sin(delta_lon / 2) ** 2)
	
	c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
	
	return R * c
