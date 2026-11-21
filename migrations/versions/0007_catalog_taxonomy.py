"""add versioned catalog taxonomy

Revision ID: 0007_catalog_taxonomy
Revises: 0006_intent_first_whatsapp
Create Date: 2026-09-06
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_catalog_taxonomy"
down_revision = "0006_intent_first_whatsapp"
branch_labels = None
depends_on = None


APPROVAL_STATUSES = "'pending', 'approved', 'revise', 'rejected'"
VERSION_STATUSES = "'draft', 'approved', 'active', 'retired'"


def upgrade() -> None:
    op.create_table(
        "taxonomy_versions",
        sa.Column("version_id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            f"status IN ({VERSION_STATUSES})",
            name="ck_taxonomy_versions_status",
        ),
    )
    op.create_index("ix_taxonomy_versions_status", "taxonomy_versions", ["status"])
    op.create_index(
        "uq_taxonomy_versions_one_active",
        "taxonomy_versions",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "product_classes",
        sa.Column("class_id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "parent_class_id",
            sa.String(),
            sa.ForeignKey("product_classes.class_id"),
            nullable=True,
        ),
        sa.Column("approval_status", sa.String(), nullable=False, server_default="pending"),
        sa.CheckConstraint(
            f"approval_status IN ({APPROVAL_STATUSES})",
            name="ck_product_classes_approval_status",
        ),
    )

    op.create_table(
        "product_families",
        sa.Column("family_id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "class_id",
            sa.String(),
            sa.ForeignKey("product_classes.class_id"),
            nullable=False,
        ),
        sa.Column("emdn_code", sa.String(), nullable=True),
        sa.Column("gmdn_code", sa.String(), nullable=True),
        sa.Column("approval_status", sa.String(), nullable=False, server_default="pending"),
        sa.CheckConstraint(
            f"approval_status IN ({APPROVAL_STATUSES})",
            name="ck_product_families_approval_status",
        ),
    )
    op.create_index("ix_product_families_class_id", "product_families", ["class_id"])

    op.create_table(
        "taxonomy_version_families",
        sa.Column(
            "version_id",
            sa.String(),
            sa.ForeignKey("taxonomy_versions.version_id"),
            primary_key=True,
        ),
        sa.Column(
            "family_id",
            sa.String(),
            sa.ForeignKey("product_families.family_id"),
            primary_key=True,
        ),
    )

    op.create_table(
        "product_taxonomy_assignments",
        sa.Column(
            "version_id",
            sa.String(),
            sa.ForeignKey("taxonomy_versions.version_id"),
            primary_key=True,
        ),
        sa.Column(
            "product_id",
            sa.String(),
            sa.ForeignKey("products.product_id"),
            primary_key=True,
        ),
        sa.Column(
            "family_id",
            sa.String(),
            sa.ForeignKey("product_families.family_id"),
            nullable=False,
        ),
        sa.Column("approval_status", sa.String(), nullable=False, server_default="pending"),
        sa.CheckConstraint(
            f"approval_status IN ({APPROVAL_STATUSES})",
            name="ck_product_taxonomy_assignments_approval_status",
        ),
    )
    op.create_index(
        "ix_product_taxonomy_assignments_family_id",
        "product_taxonomy_assignments",
        ["family_id"],
    )

    op.create_table(
        "clinical_specialties",
        sa.Column("specialty_code", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "product_specialties",
        sa.Column(
            "version_id",
            sa.String(),
            sa.ForeignKey("taxonomy_versions.version_id"),
            primary_key=True,
        ),
        sa.Column(
            "product_id",
            sa.String(),
            sa.ForeignKey("products.product_id"),
            primary_key=True,
        ),
        sa.Column(
            "specialty_code",
            sa.String(),
            sa.ForeignKey("clinical_specialties.specialty_code"),
            primary_key=True,
        ),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approval_status", sa.String(), nullable=False, server_default="pending"),
        sa.CheckConstraint(
            f"approval_status IN ({APPROVAL_STATUSES})",
            name="ck_product_specialties_approval_status",
        ),
    )
    op.create_index(
        "ix_product_specialties_product_version",
        "product_specialties",
        ["product_id", "version_id"],
    )

    op.create_table(
        "product_attributes",
        sa.Column(
            "version_id",
            sa.String(),
            sa.ForeignKey("taxonomy_versions.version_id"),
            primary_key=True,
        ),
        sa.Column(
            "product_id",
            sa.String(),
            sa.ForeignKey("products.product_id"),
            primary_key=True,
        ),
        sa.Column("attribute_code", sa.String(), primary_key=True),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("approval_status", sa.String(), nullable=False, server_default="pending"),
        sa.CheckConstraint(
            f"approval_status IN ({APPROVAL_STATUSES})",
            name="ck_product_attributes_approval_status",
        ),
    )
    op.create_index(
        "ix_product_attributes_product_version",
        "product_attributes",
        ["product_id", "version_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_product_attributes_product_version", table_name="product_attributes")
    op.drop_table("product_attributes")
    op.drop_index("ix_product_specialties_product_version", table_name="product_specialties")
    op.drop_table("product_specialties")
    op.drop_table("clinical_specialties")
    op.drop_index(
        "ix_product_taxonomy_assignments_family_id",
        table_name="product_taxonomy_assignments",
    )
    op.drop_table("product_taxonomy_assignments")
    op.drop_table("taxonomy_version_families")
    op.drop_index("ix_product_families_class_id", table_name="product_families")
    op.drop_table("product_families")
    op.drop_table("product_classes")
    op.drop_index("uq_taxonomy_versions_one_active", table_name="taxonomy_versions")
    op.drop_index("ix_taxonomy_versions_status", table_name="taxonomy_versions")
    op.drop_table("taxonomy_versions")
