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


## Functional Features
- Reciept photo recognition
- Reciept self input
- Setup recurring payments
- Analysis of finantial data

## UI Features
- Graphs
- Recap
- ...

## ToDo:
- image 
- gemini api call
- mongodb

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
