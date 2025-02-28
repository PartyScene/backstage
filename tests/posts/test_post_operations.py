import pytest
from faker import Faker
from httpx import AsyncClient
from test_posts_base import TestPostsBase
from datetime import datetime
import io

fake = Faker()

@pytest.mark.asyncio
class TestPostOperations(TestPostsBase):
    async def test_create_post(self, posts_client, mock_event):
        """Test creating a new post."""
        files = {
            'file': ('test_image.jpg', io.BytesIO(b'fake image content'), 'image/jpeg')
        }
        post_data = {
            "title": fake.sentence(),
            "content": fake.text(),
            'event': mock_event['id'],
            'type': 'image'
        }
        
        response = await self.create_post(posts_client, files, post_data)
        assert response.status_code == 201
        created_post = await response.get_json()
        
        assert created_post['title'] == post_data['title']
        assert 'id' in created_post
        assert created_post['author_id'] == post_data['author_id']

    async def test_fetch_event_posts(self, posts_client, mock_event):
        """Test retrieving a post."""
        # First create a post
        files = {
            'file': ('test_image.jpg', io.BytesIO(b'fake image content'), 'image/jpeg')
        }
        post_data = {
            "title": fake.sentence(),
            "content": fake.text(),
            'event': mock_event['id'],
            'type': 'image'
        }
        create_response = await self.create_post(posts_client, files, post_data)
        post_id = await create_response.get_json()['id']
        
        response = await posts_client.get(f"/event/{mock_event['id']}/posts")
        assert response.status_code == 200
        posts = await response.get_json()
        
        assert len(posts) >= 1
    #     assert post['title'] == post_data['title']
    #     assert post_data['content'] == post_data['content']

    # async def test_update_post(self, async_client):
    #     """Test updating a post."""
    #     # First create a post
    #     post_data = {
    #         "title": fake.sentence(),
    #         "content": fake.text()
    #     }
    #     create_response = await async_client.post("/posts", json=post_data)
    #     post_id = create_response.json()['id']
        
    #     # Update post
    #     update_data = {
    #         "title": fake.sentence(),
    #         "content": fake.text(),
    #         "tags": [fake.word() for _ in range(3)]
    #     }
        
    #     response = await async_client.put(f"/posts/{post_id}", json=update_data)
    #     assert response.status_code == 200
    #     updated_post = response.json()
        
    #     assert updated_post['title'] == update_data['title']
    #     assert updated_post['content'] == update_data['content']

    async def test_delete_post(self, posts_client, mock_event):
        """Test deleting a post."""
        # First create a post
        files = {
            'file': ('test_image.jpg', io.BytesIO(b'fake image content'), 'image/jpeg')
        }
        post_data = {
            "title": fake.sentence(),
            "content": fake.text(),
            'event': mock_event['id'],
            'type': 'image'
        }
        create_response = await self.create_post(posts_client, files, post_data)
        post_id = await create_response.get_json()['id']
        
        response = await self.fetch_post(posts_client, post_id)
        assert response.status_code == 200
        posts = await response.get_json()
        
        assert len(posts) >= 1
        
        # Delete the post
        response = await self.delete_post(posts_client, post_id)
        assert response.status_code == 204
        
        # Verify post is deleted
        get_response = await self.fetch_post(posts_client, post_id)
        assert get_response.status_code == 404

    # async def test_like_post(self, async_client):
    #     """Test liking a post."""
    #     # First create a post
    #     post_data = {"title": fake.sentence(), "content": fake.text()}
    #     create_response = await async_client.post("/posts", json=post_data)
    #     post_id = create_response.json()['id']
        
    #     response = await async_client.post(f"/posts/{post_id}/like")
    #     assert response.status_code == 200
    #     like_response = response.json()
        
    #     assert like_response['likes_count'] > 0

    # async def test_comment_on_post(self, async_client):
    #     """Test commenting on a post."""
    #     # First create a post
    #     post_data = {"title": fake.sentence(), "content": fake.text()}
    #     create_response = await async_client.post("/posts", json=post_data)
    #     post_id = create_response.json()['id']
        
    #     # Add comment
    #     comment_data = {
    #         "content": fake.text(),
    #         "author_id": fake.uuid4()
    #     }
    #     response = await async_client.post(f"/posts/{post_id}/comments", json=comment_data)
    #     assert response.status_code == 201
        
    #     # Get comments
    #     comments_response = await async_client.get(f"/posts/{post_id}/comments")
    #     assert comments_response.status_code == 200
    #     comments = comments_response.json()
        
    #     assert isinstance(comments, list)
    #     assert len(comments) > 0

    @pytest.mark.parametrize("invalid_data", [
        {"title": ""},  # Empty title
        {"content": ""},  # Empty content
        {"visibility": "invalid"}  # Invalid visibility option
    ])
    async def test_create_invalid_post(self, posts_client, invalid_data):
        """Test post creation with invalid data."""
        response = await self.create_post(posts_client, invalid_data)
        assert response.status_code == 400

    # @pytest.mark.performance
    # def test_post_retrieval_performance(self, benchmark, async_client):
    #     """Benchmark post retrieval performance."""
    #     # First create a post
    #     post_data = {"title": fake.sentence(), "content": fake.text()}
    #     create_response = async_client.post("/posts", json=post_data)
    #     post_id = create_response.json()['id']
        
    #     result = benchmark(async_client.get, f"/posts/{post_id}")
    #     assert result.status_code == 200