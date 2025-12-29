from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.models import Article
from app.schemas.article import ArticleCreate, ArticleRead, ArticleUpdate


router = APIRouter()


@router.get("/", response_model=list[ArticleRead])
def list_articles(db: Session = Depends(get_db)):
    articles = db.query(Article).all()
    return articles


@router.get("/{id}", response_model=ArticleRead)
def get_article(id: int, db: Session = Depends(get_db)):
    article = db.query(Article).filter(Article.id == id).first()
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")
    return article


@router.post("/", response_model=ArticleRead, status_code=status.HTTP_201_CREATED)
def create_article(data: ArticleCreate, db: Session = Depends(get_db)):
    existing = db.query(Article).filter(Article.code == data.code).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Article code already exists")

    article = Article(code=data.code, name=data.name)
    db.add(article)
    db.commit()
    db.refresh(article)
    return article


@router.put("/{id}", response_model=ArticleRead)
def update_article(id: int, data: ArticleCreate, db: Session = Depends(get_db)):
    article = db.query(Article).filter(Article.id == id).first()
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    if data.code != article.code:
        existing = db.query(Article).filter(Article.code == data.code, Article.id != id).first()
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Article code already exists")

    article.code = data.code
    article.name = data.name
    db.commit()
    db.refresh(article)
    return article


@router.patch("/{id}", response_model=ArticleRead)
def partial_update_article(id: int, data: ArticleUpdate, db: Session = Depends(get_db)):
    article = db.query(Article).filter(Article.id == id).first()
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    update_data = data.dict(exclude_unset=True)

    if "code" in update_data:
        existing = db.query(Article).filter(Article.code == update_data["code"], Article.id != id).first()
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Article code already exists")
        article.code = update_data["code"]

    if "name" in update_data:
        article.name = update_data["name"]

    db.commit()
    db.refresh(article)
    return article


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_article(id: int, db: Session = Depends(get_db)):
    article = db.query(Article).filter(Article.id == id).first()
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    db.delete(article)
    db.commit()
    return None
