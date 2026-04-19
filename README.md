# Dragon Hack 2026 project - Ledger

## Description:
Our product is a cross-platoform web application, where users can track, record and analize their finances. It aims to help users keep their spendings organized in an easily viewable and understandable format. 

## Implementation description:
We used djengo as the framework of our product and MongoDB as the database. As we wished to make the uploading of new data to the website as easy as possible and as such decided to allow the implementing of images. We then used the gemini API to categorize images of receipt as well as later analize data from the database, to later display it in graph and written formats to the users. 




# Django MongoDB Backend - Project Template

This is a Django project starter template for the Django MongoDB Backend.
In order to use it with your version of Django: 

- Find your Django version. To do so from the command line, make sure you
  have Django installed and run:

```bash
django-admin --version
>> 6.0
```

## Create the Django project

From your shell, run the following command to create a new Django project
replacing the `{{ project_name }}` and `{{ version }}` sections. 

```bash
django-admin startproject {{ project_name }} --template https://github.com/mongodb-labs/django-mongodb-project/archive/refs/heads/{{ version }}.x.zip
```

For a project named `example` that runs on `django==6.0.*`
the command would look like this:

```bash
django-admin startproject example --template https://github.com/mongodb-labs/django-mongodb-project/archive/refs/heads/6.0.x.zip
```

## MongoDB setup

1. Create a local env file from the example:

```bash
cp .env.example .env
```

2. Set `MONGODB_CONNECT_STRING` to your MongoDB instance.
3. Optionally change `MONGODB_DB_NAME` if you do not want to use `DH26`.
4. Run a Django system check:

```bash
python3 manage.py check
```

The project is configured to use `django_mongodb_backend` as the default Django database engine.
