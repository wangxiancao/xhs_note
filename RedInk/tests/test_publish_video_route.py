import io


class DummyPublishService:
    def __init__(self):
        self.called_with = None

    def publish_video(self, **kwargs):
        self.called_with = kwargs
        return {
            "success": True,
            "message": "ok",
            "resolved_title": "测试标题",
        }


def test_publish_video_route_success(client, monkeypatch):
    service = DummyPublishService()
    monkeypatch.setattr(
        "backend.routes.publish_routes.get_publish_service",
        lambda: service,
    )

    response = client.post(
        "/api/publish/video",
        data={
            "title": "测试标题",
            "content": "测试正文",
            "video": (io.BytesIO(b"video-bytes"), "demo.mp4"),
            "cover": (io.BytesIO(b"cover-bytes"), "cover.png"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert service.called_with is not None
    assert service.called_with["video_filename"] == "demo.mp4"
    assert service.called_with["cover_filename"] == "cover.png"
    assert service.called_with["content"] == "测试正文"


def test_publish_video_route_requires_video(client):
    response = client.post(
        "/api/publish/video",
        data={
            "title": "测试标题",
            "content": "测试正文",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["success"] is False
    assert "video" in payload["error"]
