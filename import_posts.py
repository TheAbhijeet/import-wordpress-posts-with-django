import xml.etree.ElementTree as xml
from argparse import FileType
from datetime import datetime

import pytz
import requests
from bs4 import BeautifulSoup
from django.core.files import File
from django.core.files.temp import NamedTemporaryFile
from django.core.management.base import BaseCommand
from django.template.defaultfilters import slugify
from django.utils.timezone import make_aware
from django_summernote.utils import get_attachment_model

from articles.models import Article, Category
from djangocentral.utils import clean_external_links
from users.models import User


class Command(BaseCommand):
    """
    Usage:  python manage.py import_posts wp.xml
    """

    help = "Import Articles from wordpress XML file"

    def add_arguments(self, parser):
        """
        Make sure your exported post body includes HTML tags.
        Reference: https://codelight.eu/exporting-wordpress-posts-and-pages-with-paragraph-tags-included/
        """
        parser.add_argument("xml_file", nargs="?", type=FileType("r"))

    @staticmethod
    def get_tags_and_category(xml_post):
        tags = []
        category = ""
        for cate in xml_post.findall("category"):
            if cate.attrib["domain"] == "post_tag":
                tags.append((cate.text).lower())
            elif cate.attrib["domain"] == "category":
                category = (cate.text).lower()
        return (tags, category)

    @staticmethod
    def get_posted_at_timestamp(xml_post):
        date_time = xml_post.find("{http://wordpress.org/export/1.2/}post_date").text
        date_time_obj = datetime.strptime(date_time, "%Y-%m-%d %H:%M:%S")
        date_time_obj = make_aware(
            date_time_obj, timezone=pytz.timezone("Asia/Kolkata")
        )
        return date_time_obj

    @staticmethod
    def get_author():
        return User.objects.get(username="admin")

    @staticmethod
    def clean_external_links(link):
         href = link.attrs
         href["rel"] = "nofollow noopener noreferrer"
         href["target"] = "_blank"
         return href

    @staticmethod
    def get_slug(xml_post):
        full_link = xml_post.find("link").text
        if full_link[-1] == "/":
            full_link = full_link[:-1]
        slug = full_link.split("/")[-1]
        if slug.startswith("?p"):
            slug = slugify(xml_post.find("title").text)
        return slug

    def import_image(self, img_src):
        image = NamedTemporaryFile(delete=True, dir="mediafiles/articles")
        try:
            self.stdout.write("Downloading %s" % img_src)
            response = requests.get(img_src)
            if response.status_code == 200:
                self.stdout.write("Downloaded %s" % img_src)
                image.write(response.content)
                Attachment = get_attachment_model()
                attachment = Attachment()
                attachment.name = img_src.split("/")[-1].replace(" ", "_")
                attachment.file.save(attachment.name, File(image), save=True)
                attachment.url = attachment.file.url
                image.flush()
                self.stdout.write("Imported %s" % img_src)
                return attachment.url
        except requests.exceptions.ConnectionError:
            self.stdout.write('WARNING: Unable to connect to URL "{}".'.format(img_src))
        return

    def update_post_body(self, content):
        soup = BeautifulSoup(content, "html.parser")
        for img in soup.findAll("img"):
            img["src"] = self.import_image(img["src"])
            img["srcset"] = ""

        for link in soup.findAll("a"):
            if "djangocentral" not in link["href"]:
                link = clean_external_links(link)

        return str(soup)

    def get_category_object(self, category):
        obj, _ = Category.objects.get_or_create(name=category)
        return obj

    def handle(self, *args, **options):
        try:
            input_file = options["xml_file"]
            root = xml.parse(input_file).getroot()
            posts = root.find("channel").findall("item")
            self.stdout.write("Importing %s articles" % len(posts))
            for post in posts:
                title = post.find("title").text

                if Article.objects.filter(title=title).exists():
                    continue

                self.stdout.write("Processing %s" % title)

                content = post.find(
                    "{http://purl.org/rss/1.0/modules/content/}encoded"
                ).text

                slug = self.get_slug(post)
                tags, category = self.get_tags_and_category(post)

                content = self.update_post_body(content)
                category = self.get_category_object(category)
                posted_at = self.get_posted_at_timestamp(post)
                author = self.get_author()

                article = Article.objects.create(
                    title=title,
                    slug=slug,
                    content=content,
                    category=category,
                    posted_at=posted_at,
                    author=author,
                )
                article.tags.add(*tags)
                self.stdout.write("Created %s" % title)
        except Exception as e:
            self.stdout.write("Exception %s" % e)
