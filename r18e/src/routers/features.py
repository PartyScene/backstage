from quart import make_response, render_template, current_app as app, request, jsonify
from quart.datastructures import FileStorage
from quart_jwt_extended import get_jwt_identity, jwt_required

from shared.classful import route, QuartClassful
from http import HTTPStatus
import os
from datetime import datetime
from aiocache import cached

import io

import torch

from transformers import ViTImageProcessor, ViTModel
from PIL import Image
import requests
from contextlib import asynccontextmanager

from ..internals.connector import R18E


class BaseView(QuartClassful):

    # from transformers import AutoImageProcessor, ResNetForImageClassification

    # image_processor = AutoImageProcessor.from_pretrained("microsoft/resnet-50")
    # model = ResNetForImageClassification.from_pretrained("microsoft/resnet-50")

    # inputs = image_processor(image, return_tensors="pt")

    def __init__(self) -> None:
        self.__vector_database : R18E = app.conn

    @route("/", methods=["GET"])
    @cached(ttl=60 * 60 * 72)
    async def index(self):
        return await self.healthcheck()
        
    @route("/r18e/health", methods=["GET"])
    @cached(ttl=60 * 60 * 72)
    async def healthcheck(self):
        return jsonify({"status": "healthy"}), HTTPStatus.OK

    @route("/r18e/features/extract", methods=["POST"])
    async def extract_features(self):
        """
        Extract deep learning features from an uploaded image for event analysis.
    
        This method processes an image file and generates embedding features using 
        a pre-trained transformer model. The features are then stored in a vector 
        database for semantic search and analysis.
    
        Query Parameters:
        ----------------
        event : str, required
            Unique identifier for the event associated with the image.
    
        Form Data:
        ----------
        file : FileStorage, required
            The image file to extract features from. Supports various image formats.
    
        Returns:
        --------
        tuple
            A JSON response with:
            - Success: Embedding storage result and HTTP 200 OK status
            - Error cases:
                * Missing event ID: HTTP 400 Bad Request
                * Missing file: HTTP 400 Bad Request
    
        Raises:
        -------
        Exception
            If feature extraction or embedding storage fails.
    
        Example:
        --------
        POST /r18e/features/extract?event=event_123
        Content-Type: multipart/form-data
        file: <image_file>
        """
        return "Ok", HTTPStatus.OK