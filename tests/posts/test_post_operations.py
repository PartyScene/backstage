import pytest
from faker import Faker
from quart.datastructures import FileStorage
from test_posts_base import TestPostsBase
import io
from http import HTTPStatus

fake = Faker()


@pytest.mark.asyncio(loop_scope="session")
class TestPostOperations(TestPostsBase):
    async def test_create_post(self, posts_client, mock_post, bearer):
        """Test creating a new post."""
        files = [
            {
                "filename": fake.file_name(category="image", extension="jpg"),
                "type": "image/jpeg",
            }
        ]

        response = await self.create_post(posts_client, files, mock_post, bearer)
        assert response.status_code == HTTPStatus.CREATED

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.CREATED.phrase
        assert "data" in response_json
        created_post = response_json["data"][0]

        assert "id" in created_post
        mock_post["id"] = created_post["id"]
        assert created_post["content"] == mock_post["content"]
        assert created_post["event"] == mock_post["event"]

    async def test_fetch_post(self, posts_client, mock_post, bearer):
        """Test retrieving a specific post."""
        # Assuming mock_post fixture provides a created post ID
        response = await self.fetch_post(posts_client, mock_post["id"], bearer)
        assert response.status_code == HTTPStatus.OK

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.OK.phrase
        assert "data" in response_json
        fetched_post = response_json["data"]
        assert fetched_post["id"] == mock_post["id"]
        assert fetched_post["content"] == mock_post["content"]

    async def test_fetch_event_posts(self, posts_client, mock_event, mock_post, bearer):
        """Test retrieving posts for a specific event."""
        # Ensure mock_post is associated with mock_event
        assert (
            mock_post["event"] == mock_event["id"]
        ), "Mock post must belong to mock event"

        response = await self.fetch_event_posts(posts_client, mock_event["id"], bearer)
        assert response.status_code == HTTPStatus.OK

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.OK.phrase
        assert "data" in response_json
        posts = response_json["data"]
        assert isinstance(posts, list)
        assert len(posts) >= 1  # Assuming the mock_post is returned
        assert any(
            p["id"] == mock_post["id"] for p in posts
        )  # Check if our mock post is in the list

    async def test_create_comment(self, posts_client, mock_post, mock_comment, bearer):
        """Test creating a comment on a post."""
        comment_data = {"content": fake.text()}
        response = await self.create_comment(
            posts_client, mock_post["id"], comment_data, bearer
        )
        assert response.status_code == HTTPStatus.CREATED

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.CREATED.phrase
        assert "data" in response_json
        created_comment = response_json["data"]
        assert "id" in created_comment
        mock_comment["id"] = created_comment[
            "id"
        ]  # Store ID for potential cleanup or subsequent tests
        assert created_comment["content"] == comment_data["content"]
        # assert created_comment["post"] == mock_post["id"] # Check association
        # Store comment ID if needed
        # self.created_comment_id = created_comment["id"]

    async def test_fetch_comments(self, posts_client, mock_post, mock_comment, bearer):
        """Test fetching comments for a post."""
        # Ensure mock_comment is associated with mock_post
        # assert mock_comment["post"] == mock_post["id"], "Mock comment must belong to mock post"

        response = await self.fetch_comments(posts_client, mock_post["id"], bearer)
        assert response.status_code == HTTPStatus.OK

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.OK.phrase
        assert "data" in response_json
        data = response_json["data"]
        assert "comments" in data
        comments = data["comments"]
        assert isinstance(comments, list)
        assert len(comments) >= 1
        print(comments)
        assert any(c["id"] == mock_comment["id"] for c in comments)

        # # Verify deletion
        # fetch_response = await self.fetch_comments(posts_client, mock_post["id"], bearer)
        # fetch_json = await fetch_response.get_json()
        # comments = fetch_json.get("data", [])
        # assert not any(c["id"] == mock_comment["id"] for c in comments)

    # Add tests for fetching non-existent posts/comments, unauthorized actions, etc.

    async def test_report_post_success(self, posts_client, mock_post, bearer):
        """Test reporting a post successfully."""
        report_data = {"reason": fake.sentence()}
        response = await self.report_post(
            posts_client, mock_post["id"], report_data, bearer
        )
        assert response.status_code == HTTPStatus.CREATED
        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.CREATED.phrase
        assert "Resource reported" in response_json["message"]
        assert "data" in response_json and "id" in response_json["data"]

    async def test_report_post_missing_reason(self, posts_client, mock_post, bearer):
        """Test reporting a post without a reason."""
        report_data = {}
        response = await self.report_post(
            posts_client, mock_post["id"], report_data, bearer
        )
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_json = await response.get_json()
        assert "Reason is required" in response_json["message"]

    async def test_report_comment_success(
        self, posts_client, mock_post, mock_comment, bearer
    ):
        """Test reporting a comment successfully."""
        report_data = {"reason": fake.sentence()}
        response = await self.report_comment(
            posts_client, mock_post["id"], mock_comment["id"], report_data, bearer
        )
        assert response.status_code == HTTPStatus.CREATED
        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.CREATED.phrase
        assert "Resource reported" in response_json["message"]
        assert "data" in response_json and "id" in response_json["data"]

    async def test_delete_comment(self, posts_client, mock_post, mock_comment, bearer):
        """Test deleting a comment."""
        response = await self.delete_comment(
            posts_client, mock_post["id"], mock_comment["id"], bearer
        )
        assert response.status_code == HTTPStatus.OK

        response_json = await response.get_json()
        assert response_json["status"] == HTTPStatus.OK.phrase
        assert "deleted successfully" in response_json["message"]

    # Add tests for reporting non-existent post/comment
    # Add tests for reporting comment with missing reason

    async def test_delete_post(self, posts_client, mock_post, bearer):
        """Test deleting a post."""
        response = await self.delete_post(posts_client, mock_post["id"], bearer)
        assert response.status_code == HTTPStatus.OK

        response_json = (
            await response.get_json()
        )  # OK might have empty body or specific message
        if response_json:  # Check if there's a body
            assert response_json["status"] == HTTPStatus.OK.phrase
            assert "deleted successfully" in response_json["message"]

        # Verify deletion by trying to fetch it again
        fetch_response = await self.fetch_post(posts_client, mock_post["id"], bearer)
        assert fetch_response.status_code == HTTPStatus.NOT_FOUND
        fetch_json = await fetch_response.get_json()
        assert fetch_json["status"] == HTTPStatus.NOT_FOUND.phrase
