"""
tests/test_relations.py
~~~~~~~~~~~~~~~~~~~~~~~
Comprehensive test coverage for every Django relationship type in demo_app.

Relationship types tested
─────────────────────────
1. ForeignKey (many-to-one)       — Post → Author, Comment → Post
2. ForeignKey (two FKs on model)  — PostRevision → Post + Editor
3. Nullable ForeignKey            — PostRevision.editor null=True / SET_NULL
4. Self-referential ForeignKey    — Category.parent → Category
5. OneToOneField                  — AuthorProfile ↔ Author (CASCADE + unique)
6. ManyToManyField (auto through) — Post.labels  ↔ Tag
7. ManyToManyField (explicit)     — Post.categories ↔ Category via PostCategory
8. Through-table extra fields     — PostCategory.order, PostCategory.pinned

All I/O runs against moto (in-process DynamoDB mock) via the mock_dynamodb
fixture defined in conftest.py.

Run individually:
    pytest tests/test_relations.py -v
"""

from __future__ import annotations

import uuid

import pytest

from demo_app.models import (
    Author,
    AuthorProfile,
    Category,
    Comment,
    Post,
    PostCategory,
    PostRevision,
    Tag,
)


# ──────────────────────────────────────────────────────── shared helpers

def _author(username: str = None) -> Author:
    username = username or f"user_{uuid.uuid4().hex[:8]}"
    return Author.objects.create(username=username, email=f"{username}@ex.com")


def _post(author: Author = None, title: str = None) -> Post:
    if author is None:
        author = _author()
    title = title or f"Post {uuid.uuid4().hex[:6]}"
    slug = title.lower().replace(" ", "-")
    return Post.objects.create(author=author, title=title, slug=slug)


def _tag(name: str = None) -> Tag:
    name = name or f"tag-{uuid.uuid4().hex[:6]}"
    return Tag.objects.create(name=name, slug=name)


def _category(name: str = None, parent: Category = None) -> Category:
    name = name or f"cat-{uuid.uuid4().hex[:6]}"
    slug = name.lower().replace(" ", "-")
    return Category.objects.create(name=name, slug=slug, parent=parent)


# ═══════════════════════════════════════════════════════════════════════════
# 1. ForeignKey (many-to-one): Post → Author
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.usefixtures("mock_dynamodb")
class TestForeignKey:
    """Basic FK: Post → Author."""

    def test_post_has_author(self):
        a = _author("fk_author")
        p = _post(a, "FK Post")
        assert p.author_id == a.id
        assert p.author.username == "fk_author"

    def test_author_reverse_relation(self):
        a = _author("rev_author")
        p1 = _post(a, "Rev Post 1")
        p2 = _post(a, "Rev Post 2")
        post_ids = set(a.posts.values_list("id", flat=True))
        assert p1.id in post_ids
        assert p2.id in post_ids

    def test_fk_filter(self):
        a1 = _author("fk_filter_a1")
        a2 = _author("fk_filter_a2")
        p1 = _post(a1, "A1 Post")
        _post(a2, "A2 Post")
        result = list(Post.objects.filter(author=a1).values_list("id", flat=True))
        assert p1.id in result

    def test_comment_fk(self):
        p = _post()
        c = Comment.objects.create(post=p, author_name="Alice", body="Hello")
        assert c.post_id == p.id
        assert c.post.title == p.title

    def test_comment_reverse_relation(self):
        p = _post()
        c1 = Comment.objects.create(post=p, author_name="Alice")
        c2 = Comment.objects.create(post=p, author_name="Bob")
        ids = set(p.comments.values_list("id", flat=True))
        assert c1.id in ids
        assert c2.id in ids

    def test_cascade_delete_removes_posts(self):
        a = _author("cascade_fk")
        p = _post(a, "Cascade Post")
        pid = p.id
        a.delete()
        assert not Post.objects.filter(id=pid).exists()

    def test_cascade_delete_removes_comments(self):
        p = _post()
        c = Comment.objects.create(post=p, author_name="Temp")
        cid = c.id
        p.delete()
        assert not Comment.objects.filter(id=cid).exists()


# ═══════════════════════════════════════════════════════════════════════════
# 2. ForeignKey (two FKs on same model): PostRevision → Post + Editor
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.usefixtures("mock_dynamodb")
class TestMultipleForeignKeys:
    """PostRevision has two FK fields: post and editor."""

    def test_create_revision_with_both_fks(self):
        a = _author("multi_fk_author")
        p = _post(a, "Multi FK Post")
        rev = PostRevision.objects.create(
            post=p,
            editor=a,
            body_snapshot="Original body.",
            revision_number=1,
        )
        assert rev.post_id == p.id
        assert rev.editor_id == a.id

    def test_access_both_related_objects(self):
        a = _author("multi_fk_access")
        p = _post(a, "Access Test Post")
        rev = PostRevision.objects.create(post=p, editor=a, revision_number=1)
        # Refresh so we go through the backend
        rev_fresh = PostRevision.objects.get(id=rev.id)
        assert rev_fresh.post.title == p.title
        assert rev_fresh.editor.username == "multi_fk_access"

    def test_reverse_relations_distinct(self):
        a = _author("multi_fk_rev")
        p = _post(a, "Multi FK Rev")
        rev1 = PostRevision.objects.create(post=p, editor=a, revision_number=1)
        rev2 = PostRevision.objects.create(post=p, editor=a, revision_number=2)
        post_rev_ids = set(p.revisions.values_list("id", flat=True))
        author_rev_ids = set(a.revisions.values_list("id", flat=True))
        assert rev1.id in post_rev_ids
        assert rev2.id in post_rev_ids
        assert rev1.id in author_rev_ids

    def test_filter_by_editor(self):
        a1 = _author("editor_a1")
        a2 = _author("editor_a2")
        p = _post(a1)
        r1 = PostRevision.objects.create(post=p, editor=a1, revision_number=1)
        r2 = PostRevision.objects.create(post=p, editor=a2, revision_number=2)
        a1_revs = list(PostRevision.objects.filter(editor=a1).values_list("id", flat=True))
        assert r1.id in a1_revs
        assert r2.id not in a1_revs


# ═══════════════════════════════════════════════════════════════════════════
# 3. Nullable ForeignKey: PostRevision.editor
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.usefixtures("mock_dynamodb")
class TestNullableForeignKey:
    """PostRevision.editor is nullable (null=True, on_delete=SET_NULL)."""

    def test_create_revision_without_editor(self):
        a = _author("nullable_fk_author")
        p = _post(a, "Nullable FK Post")
        rev = PostRevision.objects.create(
            post=p,
            editor=None,
            body_snapshot="System snapshot.",
            revision_number=1,
        )
        assert rev.editor_id is None
        assert rev.editor is None

    def test_filter_null_editor(self):
        a = _author("null_filter")
        p = _post(a)
        r_null = PostRevision.objects.create(post=p, editor=None, revision_number=1)
        r_set = PostRevision.objects.create(post=p, editor=a, revision_number=2)
        null_ids = set(PostRevision.objects.filter(editor__isnull=True).values_list("id", flat=True))
        set_ids = set(PostRevision.objects.filter(editor__isnull=False).values_list("id", flat=True))
        assert r_null.id in null_ids
        assert r_null.id not in set_ids
        assert r_set.id in set_ids
        assert r_set.id not in null_ids

    def test_set_null_on_author_delete(self):
        author = _author("set_null_editor")
        p = _post(_author("post_owner"))
        rev = PostRevision.objects.create(post=p, editor=author, revision_number=1)
        rid = rev.id
        author.delete()
        rev_fresh = PostRevision.objects.get(id=rid)
        assert rev_fresh.editor_id is None

    def test_update_editor_to_none(self):
        a = _author("update_to_none")
        p = _post(a)
        rev = PostRevision.objects.create(post=p, editor=a, revision_number=1)
        rev.editor = None
        rev.save()
        rev_fresh = PostRevision.objects.get(id=rev.id)
        assert rev_fresh.editor_id is None

    def test_update_editor_from_none(self):
        a = _author("update_from_none")
        p = _post(a)
        rev = PostRevision.objects.create(post=p, editor=None, revision_number=1)
        rev.editor = a
        rev.save()
        rev_fresh = PostRevision.objects.get(id=rev.id)
        assert rev_fresh.editor_id == a.id


# ═══════════════════════════════════════════════════════════════════════════
# 4. Self-referential ForeignKey: Category.parent
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.usefixtures("mock_dynamodb")
class TestSelfReferentialFK:
    """Category.parent = ForeignKey('self', null=True, on_delete=SET_NULL)."""

    def test_root_category_has_no_parent(self):
        root = _category("Tech")
        assert root.parent_id is None
        assert root.parent is None

    def test_child_has_parent(self):
        root = _category("Science")
        child = _category("Physics", parent=root)
        assert child.parent_id == root.id

    def test_access_parent_object(self):
        root = _category("History")
        child = _category("Ancient History", parent=root)
        child_fresh = Category.objects.get(id=child.id)
        assert child_fresh.parent.name == "History"

    def test_children_reverse_relation(self):
        root = _category("Engineering")
        c1 = _category("Software", parent=root)
        c2 = _category("Hardware", parent=root)
        children_ids = set(root.children.values_list("id", flat=True))
        assert c1.id in children_ids
        assert c2.id in children_ids

    def test_three_level_hierarchy(self):
        level1 = _category("L1")
        level2 = _category("L2", parent=level1)
        level3 = _category("L3", parent=level2)
        # Traverse from leaf to root
        l3_fresh = Category.objects.get(id=level3.id)
        assert l3_fresh.parent_id == level2.id
        l2_fresh = Category.objects.get(id=level2.id)
        assert l2_fresh.parent_id == level1.id

    def test_filter_by_parent(self):
        root = _category("Root")
        other = _category("Other Root")
        child = _category("Child", parent=root)
        root_children = list(
            Category.objects.filter(parent=root).values_list("id", flat=True)
        )
        assert child.id in root_children
        other_children = list(
            Category.objects.filter(parent=other).values_list("id", flat=True)
        )
        assert child.id not in other_children

    def test_set_null_on_parent_delete(self):
        parent = _category("To Be Deleted")
        child = _category("Orphan Child", parent=parent)
        cid = child.id
        parent.delete()
        child_fresh = Category.objects.get(id=cid)
        assert child_fresh.parent_id is None

    def test_filter_root_categories(self):
        root1 = _category("Root1")
        root2 = _category("Root2")
        _category("ChildA", parent=root1)
        roots = set(
            Category.objects.filter(parent__isnull=True).values_list("id", flat=True)
        )
        assert root1.id in roots
        assert root2.id in roots


# ═══════════════════════════════════════════════════════════════════════════
# 5. OneToOneField: AuthorProfile ↔ Author
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.usefixtures("mock_dynamodb")
class TestOneToOneField:
    """AuthorProfile.author = OneToOneField(Author, on_delete=CASCADE)."""

    def test_create_profile(self):
        a = _author("oto_author")
        prof = AuthorProfile.objects.create(
            author=a,
            website="https://example.com",
            twitter="@oto_author",
        )
        assert prof.author_id == a.id

    def test_forward_accessor(self):
        a = _author("oto_forward")
        prof = AuthorProfile.objects.create(author=a, twitter="@fwd")
        prof_fresh = AuthorProfile.objects.get(id=prof.id)
        assert prof_fresh.author.username == "oto_forward"

    def test_reverse_accessor(self):
        a = _author("oto_reverse")
        AuthorProfile.objects.create(author=a, website="https://reverse.io")
        # Access via author.profile
        a_fresh = Author.objects.get(id=a.id)
        assert a_fresh.profile.website == "https://reverse.io"

    def test_cascade_delete_removes_profile(self):
        a = _author("oto_cascade")
        prof = AuthorProfile.objects.create(author=a)
        pid = prof.id
        a.delete()
        assert not AuthorProfile.objects.filter(id=pid).exists()

    def test_profile_fields_update(self):
        a = _author("oto_update")
        prof = AuthorProfile.objects.create(author=a, follower_count=100)
        prof.follower_count = 200
        prof.save()
        prof_fresh = AuthorProfile.objects.get(id=prof.id)
        assert prof_fresh.follower_count == 200

    def test_filter_by_author(self):
        a1 = _author("oto_filter_a1")
        a2 = _author("oto_filter_a2")
        p1 = AuthorProfile.objects.create(author=a1)
        AuthorProfile.objects.create(author=a2)
        result = list(AuthorProfile.objects.filter(author=a1).values_list("id", flat=True))
        assert p1.id in result
        assert len(result) == 1


# ═══════════════════════════════════════════════════════════════════════════
# 6. ManyToManyField (auto through table): Post.labels ↔ Tag
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.usefixtures("mock_dynamodb")
class TestManyToManyAuto:
    """Post.labels = ManyToManyField(Tag) — auto-created join table."""

    def test_add_single_tag(self):
        p = _post()
        t = _tag("python")
        p.labels.add(t)
        label_ids = list(p.labels.values_list("id", flat=True))
        assert t.id in label_ids

    def test_add_multiple_tags(self):
        p = _post()
        t1 = _tag("django")
        t2 = _tag("api")
        t3 = _tag("ddb")
        p.labels.add(t1, t2, t3)
        label_ids = set(p.labels.values_list("id", flat=True))
        assert {t1.id, t2.id, t3.id}.issubset(label_ids)

    def test_remove_tag(self):
        p = _post()
        t = _tag("to-remove")
        p.labels.add(t)
        p.labels.remove(t)
        label_ids = list(p.labels.values_list("id", flat=True))
        assert t.id not in label_ids

    def test_clear_all_tags(self):
        p = _post()
        p.labels.add(_tag("clear-a"), _tag("clear-b"))
        p.labels.clear()
        assert p.labels.count() == 0

    def test_reverse_accessor(self):
        t = _tag("shared-tag")
        p1 = _post()
        p2 = _post()
        p1.labels.add(t)
        p2.labels.add(t)
        post_ids = set(t.posts.values_list("id", flat=True))
        assert p1.id in post_ids
        assert p2.id in post_ids

    def test_same_tag_not_duplicated(self):
        p = _post()
        t = _tag("unique-add")
        p.labels.add(t)
        p.labels.add(t)  # adding same tag twice
        assert p.labels.filter(id=t.id).count() == 1

    def test_m2m_count(self):
        p = _post()
        tags = [_tag(f"count-tag-{i}") for i in range(5)]
        for t in tags:
            p.labels.add(t)
        assert p.labels.count() == 5

    def test_set_replaces_tags(self):
        p = _post()
        t_old = _tag("old-label")
        t_new = _tag("new-label")
        p.labels.add(t_old)
        p.labels.set([t_new])
        label_ids = list(p.labels.values_list("id", flat=True))
        assert t_new.id in label_ids
        assert t_old.id not in label_ids

    def test_filter_posts_by_tag(self):
        t = _tag("filter-by-tag")
        p1 = _post()
        p2 = _post()
        p1.labels.add(t)
        matching = list(Post.objects.filter(labels=t).values_list("id", flat=True))
        assert p1.id in matching
        assert p2.id not in matching


# ═══════════════════════════════════════════════════════════════════════════
# 7. ManyToManyField (explicit through): Post.categories ↔ Category
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.usefixtures("mock_dynamodb")
class TestManyToManyExplicitThrough:
    """
    Post.categories = ManyToManyField(Category, through='PostCategory').
    Tests both the M2M interface and direct through-table access.
    """

    def test_create_through_instance(self):
        p = _post()
        c = _category("Tutorials")
        pc = PostCategory.objects.create(post=p, category=c, order=1)
        assert pc.post_id == p.id
        assert pc.category_id == c.id
        assert pc.order == 1

    def test_access_categories_via_m2m(self):
        p = _post()
        c1 = _category("News")
        c2 = _category("Opinion")
        PostCategory.objects.create(post=p, category=c1, order=0)
        PostCategory.objects.create(post=p, category=c2, order=1)
        cat_ids = set(p.categories.values_list("id", flat=True))
        assert c1.id in cat_ids
        assert c2.id in cat_ids

    def test_reverse_posts_from_category(self):
        p1 = _post()
        p2 = _post()
        c = _category("Shared Cat")
        PostCategory.objects.create(post=p1, category=c, order=0)
        PostCategory.objects.create(post=p2, category=c, order=1)
        post_ids = set(c.posts.values_list("id", flat=True))
        assert p1.id in post_ids
        assert p2.id in post_ids

    def test_through_table_extra_fields(self):
        p = _post()
        c = _category("Pinned Cat")
        pc = PostCategory.objects.create(post=p, category=c, order=5, pinned=True)
        pc_fresh = PostCategory.objects.get(id=pc.id)
        assert pc_fresh.order == 5
        assert pc_fresh.pinned is True

    def test_filter_through_by_extra_field(self):
        p = _post()
        c1 = _category("Cat Pinned")
        c2 = _category("Cat Not Pinned")
        pc1 = PostCategory.objects.create(post=p, category=c1, order=0, pinned=True)
        pc2 = PostCategory.objects.create(post=p, category=c2, order=1, pinned=False)
        pinned = list(PostCategory.objects.filter(pinned=True).values_list("id", flat=True))
        assert pc1.id in pinned
        assert pc2.id not in pinned

    def test_through_table_fk_post_cascade(self):
        p = _post()
        c = _category("Cascade Cat")
        pc = PostCategory.objects.create(post=p, category=c, order=0)
        pc_id = pc.id
        p.delete()
        assert not PostCategory.objects.filter(id=pc_id).exists()

    def test_through_table_fk_category_cascade(self):
        p = _post()
        c = _category("Delete Cat")
        pc = PostCategory.objects.create(post=p, category=c, order=0)
        pc_id = pc.id
        c.delete()
        assert not PostCategory.objects.filter(id=pc_id).exists()

    def test_direct_through_accessor(self):
        p = _post()
        c = _category("Direct Access Cat")
        PostCategory.objects.create(post=p, category=c, order=3, pinned=False)
        # Access through the `post_categories` reverse name
        pcs = list(p.post_categories.values_list("order", flat=True))
        assert 3 in pcs

    def test_update_through_extra_field(self):
        p = _post()
        c = _category("Update Cat")
        pc = PostCategory.objects.create(post=p, category=c, order=1, pinned=False)
        pc.order = 99
        pc.pinned = True
        pc.save()
        pc_fresh = PostCategory.objects.get(id=pc.id)
        assert pc_fresh.order == 99
        assert pc_fresh.pinned is True

    def test_delete_through_instance_directly(self):
        p = _post()
        c = _category("Direct Delete Cat")
        pc = PostCategory.objects.create(post=p, category=c, order=0)
        pc_id = pc.id
        pc.delete()
        assert not PostCategory.objects.filter(id=pc_id).exists()
        # Post and Category still exist
        assert Post.objects.filter(id=p.id).exists()
        assert Category.objects.filter(id=c.id).exists()


# ═══════════════════════════════════════════════════════════════════════════
# 8. Combined / cross-relation tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.usefixtures("mock_dynamodb")
class TestCrossRelation:
    """Tests that span multiple relation types together."""

    def test_author_with_profile_and_posts(self):
        """Author → Profile (1:1) + Posts (1:N)."""
        a = _author("combined_author")
        AuthorProfile.objects.create(author=a, twitter="@combined", follower_count=42)
        p1 = _post(a, "Combined Post 1")
        p2 = _post(a, "Combined Post 2")

        a_fresh = Author.objects.get(id=a.id)
        assert a_fresh.profile.follower_count == 42
        post_ids = set(a_fresh.posts.values_list("id", flat=True))
        assert p1.id in post_ids
        assert p2.id in post_ids

    def test_post_with_tags_and_categories(self):
        """Post with both auto M2M (labels) and explicit M2M (categories)."""
        a = _author("m2m_combined")
        p = _post(a, "Multi M2M Post")
        t1 = _tag("m2m-tag-a")
        t2 = _tag("m2m-tag-b")
        root_cat = _category("Root M2M")
        sub_cat = _category("Sub M2M", parent=root_cat)

        p.labels.add(t1, t2)
        PostCategory.objects.create(post=p, category=root_cat, order=0)
        PostCategory.objects.create(post=p, category=sub_cat, order=1, pinned=True)

        assert p.labels.count() == 2
        assert p.categories.count() == 2
        assert p.post_categories.filter(pinned=True).count() == 1

    def test_post_revision_with_nullable_editor_and_cascade(self):
        """PostRevision with nullable editor; cascade delete cleans up revision."""
        a = _author("rev_combined")
        p = _post(a, "Revision Post")
        rev_with = PostRevision.objects.create(post=p, editor=a, revision_number=1)
        rev_without = PostRevision.objects.create(post=p, editor=None, revision_number=2)

        p_fresh = Post.objects.get(id=p.id)
        rev_ids = set(p_fresh.revisions.values_list("id", flat=True))
        assert rev_with.id in rev_ids
        assert rev_without.id in rev_ids

        # CASCADE: delete post removes revisions
        pid = p.id
        p.delete()
        assert not PostRevision.objects.filter(post_id=pid).exists()

    def test_category_tree_with_posts(self):
        """Self-ref FK tree + Posts in each node."""
        tech = _category("Tech Root")
        backend = _category("Backend", parent=tech)
        frontend = _category("Frontend", parent=tech)
        a = _author("tree_author")
        p_back = _post(a, "Backend Post")
        p_front = _post(a, "Frontend Post")
        PostCategory.objects.create(post=p_back, category=backend, order=0)
        PostCategory.objects.create(post=p_front, category=frontend, order=0)

        # All children of tech
        children_ids = set(tech.children.values_list("id", flat=True))
        assert backend.id in children_ids
        assert frontend.id in children_ids

        # Posts via category
        back_post_ids = set(backend.posts.values_list("id", flat=True))
        assert p_back.id in back_post_ids

    def test_full_object_graph(self):
        """
        Exercises every relation type in a single connected object graph:
          Author + Profile + Posts + Tags + Categories (tree) + PostCategory
          + Revisions (with + without editor)
        """
        # ── Authors
        alice = _author("alice_graph")
        bob = _author("bob_graph")
        AuthorProfile.objects.create(author=alice, twitter="@alice", follower_count=100)
        AuthorProfile.objects.create(author=bob, location="NYC")

        # ── Tags
        t_python = _tag("python-graph")
        t_web = _tag("web-graph")

        # ── Category tree
        root = _category("Graph Root")
        sub = _category("Graph Sub", parent=root)

        # ── Posts
        post1 = _post(alice, "Alice's Featured Post")
        post2 = _post(bob, "Bob's Tutorial")

        # ── M2M auto (labels)
        post1.labels.add(t_python, t_web)
        post2.labels.add(t_python)

        # ── M2M explicit (categories via PostCategory)
        PostCategory.objects.create(post=post1, category=root, order=0, pinned=True)
        PostCategory.objects.create(post=post1, category=sub, order=1)
        PostCategory.objects.create(post=post2, category=sub, order=0)

        # ── Comments
        Comment.objects.create(post=post1, author_name="Reader1", body="Great!")
        Comment.objects.create(post=post1, author_name="Reader2", body="Thanks!")

        # ── Revisions (with + without editor)
        PostRevision.objects.create(post=post1, editor=alice, revision_number=1,
                                    change_summary="Initial draft")
        PostRevision.objects.create(post=post1, editor=None, revision_number=2,
                                    change_summary="Auto-format")

        # ── Assertions: all relations accessible
        assert alice.profile.twitter == "@alice"
        assert bob.profile.location == "NYC"
        assert post1.labels.count() == 2
        assert post2.labels.count() == 1
        assert post1.categories.count() == 2
        assert post1.post_categories.filter(pinned=True).count() == 1
        assert post1.comments.count() == 2
        assert post1.revisions.count() == 2
        assert post1.revisions.filter(editor__isnull=True).count() == 1
        assert sub.parent.name == "Graph Root"
        assert sub.posts.count() == 2   # post1 + post2
