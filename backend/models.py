"""ORM models for the eight core tables (see docs/03_database_er_design.md).

Field sets intentionally mirror the Day1 ER contract. Extra per-case attributes
that are not part of the eight tables (spacing, status, slice_count, ...) live in
a per-case ``metadata.json`` as agreed in docs/01, not as new columns here.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, nullable=False)
    role = Column(String, nullable=False, default="annotator")


class Case(Base):
    __tablename__ = "cases"

    case_id = Column(String, primary_key=True)
    patient_id = Column(String, index=True)
    modality = Column(String)
    create_time = Column(DateTime, default=_utcnow)


class Image(Base):
    __tablename__ = "images"

    image_id = Column(String, primary_key=True)
    case_id = Column(String, ForeignKey("cases.case_id"), index=True)
    path = Column(String, nullable=False)
    width = Column(Integer)
    height = Column(Integer)


class Annotation(Base):
    __tablename__ = "annotations"

    annotation_id = Column(String, primary_key=True)
    image_id = Column(String, ForeignKey("images.image_id"), index=True)
    user = Column(Integer, ForeignKey("users.id"), nullable=True)
    create_time = Column(DateTime, default=_utcnow)


class Mask(Base):
    __tablename__ = "masks"

    mask_id = Column(String, primary_key=True)
    annotation_id = Column(String, ForeignKey("annotations.annotation_id"), index=True)
    path = Column(String, nullable=False)


class Model(Base):
    __tablename__ = "models"

    model_id = Column(String, primary_key=True)
    version = Column(String)
    dice = Column(Float)


class Dataset(Base):
    __tablename__ = "datasets"

    dataset_id = Column(String, primary_key=True)
    train = Column(String)
    val = Column(String)
    test = Column(String)


class Version(Base):
    __tablename__ = "versions"

    # docs/03: a version record is identified by (version + annotation) on Day1.
    version = Column(String, primary_key=True)
    annotation = Column(String, ForeignKey("annotations.annotation_id"), primary_key=True)
    model = Column(String, ForeignKey("models.model_id"), nullable=True)
    dataset = Column(String, ForeignKey("datasets.dataset_id"), nullable=True)
