from django.urls import path
from . import views

urlpatterns = [
    path("authors/", views.AuthorListView.as_view(), name="author-list"),
    path("authors/<str:pk>/", views.AuthorDetailView.as_view(), name="author-detail"),
    path("authors/<str:pk>/posts/", views.AuthorPostsView.as_view(), name="author-posts"),
    path("posts/", views.PostListView.as_view(), name="post-list"),
    path("posts/search/", views.PostSearchView.as_view(), name="post-search"),
    path("posts/<str:pk>/", views.PostDetailView.as_view(), name="post-detail"),
    path("posts/<str:post_pk>/comments/", views.CommentCreateView.as_view(), name="comment-create"),
    path("comments/<str:pk>/", views.CommentDeleteView.as_view(), name="comment-delete"),
    # Author profile (OneToOne)
    path("authors/<str:pk>/profile/", views.AuthorProfileView.as_view(), name="author-profile"),
    # Tags
    path("tags/", views.TagListView.as_view(), name="tag-list"),
    path("tags/<str:pk>/", views.TagDetailView.as_view(), name="tag-detail"),
    # Categories (self-ref FK)
    path("categories/", views.CategoryListView.as_view(), name="category-list"),
    path("categories/<str:pk>/", views.CategoryDetailView.as_view(), name="category-detail"),
    # Post labels — auto M2M Post ↔ Tag
    path("posts/<str:pk>/labels/", views.PostLabelsView.as_view(), name="post-labels"),
    path("posts/<str:pk>/labels/<str:tag_pk>/", views.PostLabelRemoveView.as_view(), name="post-label-remove"),
    # Post categories — explicit M2M through PostCategory
    path("posts/<str:pk>/categories/", views.PostCategoriesView.as_view(), name="post-categories"),
    path("postcategories/<str:pk>/", views.PostCategoryDeleteView.as_view(), name="postcategory-delete"),
    # Post revisions (nullable FK)
    path("posts/<str:pk>/revisions/", views.PostRevisionsView.as_view(), name="post-revisions"),
]
