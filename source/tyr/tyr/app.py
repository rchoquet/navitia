#coding: utf-8

from flask import Flask
from flask.ext import restful
from flask.ext.sqlalchemy import SQLAlchemy
import logging
from tyr.config import configure_logger

app = Flask(__name__)
app.config.from_object('tyr.default_settings')
app.config.from_envvar('TYR_CONFIG_FILE')
app.config['SQLALCHEMY_DATABASE_URI'] = app.config['PG_CONNECTION_STRING']

configure_logger(app)

api = restful.Api(app, catch_all_404s=True)
db = SQLAlchemy(app)
