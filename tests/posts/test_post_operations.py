import pytest
from faker import Faker
from httpx import AsyncClient
from test_posts_base import TestPostsBase
from datetime import datetime
from quart.datastructures import FileStorage
import io

fake = Faker()


@pytest.mark.asyncio(loop_scope="session")
class TestPostOperations(TestPostsBase):
    async def test_create_post(
        self, posts_client, mock_event, bearer, mock_media_client
    ):
        """Test creating a new post."""
        files = {
            "file": FileStorage(
                io.BytesIO(b"fake image content"),
                filename="test_image.jpg",
                content_type="image/jpeg",
            )
        }
        post_data = {
            "title": fake.sentence(),
            "content": fake.text(),
            "event": mock_event["id"],
            "type": "image",
        }

        mock_media_client.upload_media.return_value = {
            "type": "image/jpeg",
            "url": "https://storage.googleapis.com/fake-bucket/test-image.jpg",
            "creator": "xxxxx",
            "event": "xxxxxxx",
            "id": "test",
        }
        response = await self.create_post(posts_client, files, post_data, bearer)
        assert response.status_code == 201
        created_post = await response.get_json()
        print(created_post)
        assert isinstance(created_post, dict)
        assert "id" in created_post

    async def test_fetch_event_posts(self, posts_client, mock_event, bearer):
        """Test retrieving a post."""
        # First create a post
        files = {
            "file": FileStorage(
                io.BytesIO(b"fake image content"),
                filename=fake.file_name(category="image", extension="jpg"),
                content_type="image/jpeg",
            )
        }
        post_data = {
            "title": fake.sentence(),
            "content": fake.text(),
            "event": mock_event["id"],
            "type": "image",
        }
        create_response = await self.create_post(posts_client, files, post_data, bearer)
        post_data = await create_response.get_json()
        assert create_response.status_code == 201
        post_id = post_data["id"]

        response = await self.fetch_event_posts(posts_client, mock_event["id"], bearer)
        assert response.status_code == 200
        posts = await response.get_json()
        print(posts)
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

    async def test_delete_post(self, posts_client, mock_event, bearer):
        """Test deleting a post."""
        # First create a post
        files = {
            "file": FileStorage(
                io.BytesIO(b"fake image content"),
                filename=fake.file_name(category="image", extension="jpg"),
                content_type="image/jpeg",
            )
        }
        post_data = {
            "title": fake.sentence(),
            "content": fake.text(),
            "event": mock_event["id"],
            "type": "image",
        }
        create_response = await self.create_post(posts_client, files, post_data, bearer)
        post_data = await create_response.get_json()
        assert create_response.status_code == 201
        post_id = post_data["id"]

        response = await self.fetch_post(posts_client, post_id, bearer)
        assert response.status_code == 200
        posts = await response.get_json()

        assert len(posts) >= 1

        # Delete the post
        response = await self.delete_post(posts_client, post_id, bearer)
        assert response.status_code == 204

        # Verify post is deleted
        get_response = await self.fetch_post(posts_client, post_id, bearer)
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

    async def test_create_post_comment(self, posts_client, mock_event, bearer):
        """Test commenting on a post."""
        # First create a post
        files = {
            "file": FileStorage(
                io.BytesIO(b"fake image content"),
                filename=fake.file_name(category="image", extension="jpg"),
                content_type="image/jpeg",
            )
        }
        post_data = {
            "title": fake.sentence(),
            "content": fake.text(),
            "event": mock_event["id"],
            "type": "image",
        }
        create_response = await self.create_post(posts_client, files, post_data, bearer)
        post_data = await create_response.get_json()
        assert create_response.status_code == 201
        post_id = post_data["id"]

        response = await self.fetch_post(posts_client, post_id, bearer)
        assert response.status_code == 200
        posts = await response.get_json()
        assert len(posts) >= 1

        # Add comment
        comment_data = {
            "content": fake.text(),
        }
        response = await self.create_comment(
            posts_client, post_id, comment_data, bearer
        )
        assert response.status_code == 201

    async def test_fetch_post_comments(self, posts_client, mock_event, bearer):
        # First create a post
        files = {
            "file": FileStorage(
                io.BytesIO(b"fake image content"),
                filename=fake.file_name(category="image", extension="jpg"),
                content_type="image/jpeg",
            )
        }
        post_data = {
            "title": fake.sentence(),
            "content": fake.text(),
            "event": mock_event["id"],
            "type": "image",
        }
        create_response = await self.create_post(posts_client, files, post_data, bearer)
        post_data = await create_response.get_json()
        assert create_response.status_code == 201
        post_id = post_data["id"]

        # Add comment
        comment_data = {
            "content": fake.text(),
        }
        response = await self.create_comment(
            posts_client, post_id, comment_data, bearer
        )
        assert response.status_code == 201

        # Get comments
        comments_response = await self.get_comments(posts_client, post_id, bearer)
        assert comments_response.status_code == 200
        comments = await comments_response.get_json()

        assert isinstance(comments, list)
        assert len(comments) > 0

    async def test_delete_post_comments(self, posts_client, mock_event, bearer):
        # First create a post
        files = {
            "file": FileStorage(
                io.BytesIO(b"fake image content"),
                filename=fake.file_name(category="image", extension="jpg"),
                content_type="image/jpeg",
            )
        }
        post_data = {
            "title": fake.sentence(),
            "content": fake.text(),
            "event": mock_event["id"],
            "type": "image",
        }
        create_response = await self.create_post(posts_client, files, post_data, bearer)
        post_data = await create_response.get_json()
        assert create_response.status_code == 201
        post_id = post_data["id"]

        # Add comment
        comment_data = {
            "content": fake.text(),
        }
        response = await self.create_comment(
            posts_client, post_id, comment_data, bearer
        )
        create_resp = await response.get_json()
        assert response.status_code == 201
        comment_id = create_resp["id"]

        # Get comments
        comments_response = await self.get_comments(posts_client, post_id, bearer)
        assert comments_response.status_code == 200
        comments = await comments_response.get_json()

        assert isinstance(comments, list)
        assert len(comments) > 0

        # Delete comment
        response = await self.delete_comment(posts_client, post_id, comment_id, bearer)
        assert response.status_code == 204

        # Verify comment is deleted
        get_response = await self.get_comments(posts_client, post_id, bearer)
        assert get_response.status_code == 404

    @pytest.mark.parametrize(
        "invalid_data",
        [
            {"title": ""},  # Empty title
            {"content": ""},  # Empty content
            {"visibility": "invalid"},  # Invalid visibility option
        ],
    )
    async def test_create_invalid_post(self, posts_client, invalid_data, bearer):
        """Test post creation with invalid data."""
        files = {
            "file": FileStorage(
                io.BytesIO(b"fake image content"),
                filename="test_image.jpg",
                content_type="image/jpeg",
            )
        }
        response = await self.create_post(posts_client, files, invalid_data, bearer)
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
