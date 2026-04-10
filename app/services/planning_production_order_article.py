from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.models import Article


def _build_article_not_found_detail(*, article_id: int) -> dict[str, object]:
    return {
        "code": "article_not_found",
        "message": "Article not found",
        "article_id": int(article_id),
        "field": "article_id",
        "field_metadata": {
            "description": "Requested article identifier",
            "type": "int",
        },
        "next_steps": ["use_existing_article_id"],
    }


def _require_article(
    *,
    db: Session,
    article_id: int,
    build_article_not_found_detail: Callable[..., dict[str, object]] = _build_article_not_found_detail,
) -> Article:
    article = db.query(Article).filter(Article.id == article_id).first()
    if article is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=build_article_not_found_detail(article_id=article_id),
        )
    return article
