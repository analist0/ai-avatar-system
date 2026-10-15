"""youtube projects for scripted talking-avatar uploads

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-15

Chat sessions stay real-time. A YouTube video is a different object: a script,
an aspect ratio, and the exported MP4 / SRT / chapter files.
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "youtube_projects",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("avatar_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("script", sa.Text(), nullable=False),
        sa.Column("language", sa.String(), nullable=False),
        sa.Column("aspect", sa.String(), nullable=False),
        sa.Column("burn_captions", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("engine", sa.String(), nullable=True),
        sa.Column("video_key", sa.String(), nullable=True),
        sa.Column("srt_key", sa.String(), nullable=True),
        sa.Column("chapters_key", sa.String(), nullable=True),
        sa.Column("description_key", sa.String(), nullable=True),
        sa.Column("project_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["avatar_id"], ["avatars.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_youtube_projects_user_id", "youtube_projects", ["user_id"])
    op.create_index("ix_youtube_projects_avatar_id", "youtube_projects", ["avatar_id"])
    op.create_index("ix_youtube_projects_status", "youtube_projects", ["status"])
    op.create_index(
        "ix_youtube_projects_user_created",
        "youtube_projects",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_youtube_projects_user_created", table_name="youtube_projects")
    op.drop_index("ix_youtube_projects_status", table_name="youtube_projects")
    op.drop_index("ix_youtube_projects_avatar_id", table_name="youtube_projects")
    op.drop_index("ix_youtube_projects_user_id", table_name="youtube_projects")
    op.drop_table("youtube_projects")
