import os
import datetime
from flask import Flask, Blueprint, request, jsonify, send_file
from flask_pymongo import PyMongo
from bson import ObjectId
from pymongo import DESCENDING
from werkzeug.utils import secure_filename
import cloudinary
import cloudinary.uploader
from io import BytesIO
import requests

# ----------------- INIT APP ------------------
app = Flask(__name__)

# Replace with your actual Mongo URI
app.config["MONGO_URI"] = os.getenv("MONGO_URI", "mongodb+srv://username:password@cluster.mongodb.net/naits_db?retryWrites=true&w=majority")
mongo = PyMongo(app)
db = mongo.db

# ----------------- CLOUDINARY CONFIG ------------
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME", "dhndd1msa"),
    api_key=os.getenv("CLOUDINARY_API_KEY", "337382597786761"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET", "bEJ0sWFZi8yYzeP5lzVl_rmUtX8")
)

# ----------------- BLUEPRINT ------------------
resources_bp = Blueprint('resources_bp', __name__, url_prefix='/api/resources')
resources_collection = db.resources

# ----------------- HELPERS ------------------
def serialize_resource(res):
    res['_id'] = str(res['_id'])
    return res

def get_file_extension(file_type):
    ext_map = {'pdf': '.pdf', 'doc': '.doc', 'mp3': '.mp3', 'mp4': '.mp4', 'img': '.jpg'}
    return ext_map.get(file_type.lower(), '')

def download_and_convert(url, original_filename, file_type):
    try:
        response = requests.get(url)
        response.raise_for_status()
        file_data = BytesIO(response.content)
        filename = secure_filename(original_filename)
        base, ext = os.path.splitext(filename)
        correct_ext = get_file_extension(file_type)
        if not ext or ext.lower() != correct_ext:
            filename = f"{base}{correct_ext}"
        return file_data, filename
    except Exception as e:
        raise RuntimeError(f"Download error: {e}")

# ----------------- ROUTES ------------------

@resources_bp.route('/upload', methods=['POST'])
def upload_resource():
    try:
        fields = ['title', 'level', 'department', 'category', 'file_type']
        data = {field: request.form.get(field) for field in fields}
        file = request.files.get('file')
        if None in data.values() or not file:
            return jsonify(success=False, error="All fields are required"), 400

        upload_result = cloudinary.uploader.upload(
            file,
            resource_type="auto",
            folder="naits_resources",
            use_filename=True,
            unique_filename=False
        )
        if not upload_result.get("secure_url"):
            return jsonify(success=False, error="Upload failed"), 500

        new_resource = {
            'title': data['title'],
            'file_url': upload_result["secure_url"],
            'file_type': data['file_type'].lower(),
            'level': data['level'],
            'department': data['department'],
            'category': data['category'],
            'created_at': datetime.datetime.utcnow(),
            'cloudinary_public_id': upload_result.get('public_id'),
            'original_filename': secure_filename(file.filename)
        }
        inserted = resources_collection.insert_one(new_resource)
        new_resource['_id'] = str(inserted.inserted_id)
        return jsonify(success=True, resource=new_resource), 201
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500

@resources_bp.route('/download/<resource_id>', methods=['GET'])
def download_resource(resource_id):
    try:
        resource = resources_collection.find_one({'_id': ObjectId(resource_id)})
        if not resource:
            return jsonify(success=False, error='Not found'), 404
        file_data, filename = download_and_convert(
            resource['file_url'],
            resource.get('original_filename', resource['title']),
            resource['file_type']
        )
        return send_file(file_data, as_attachment=True, download_name=filename,
                         mimetype=f"application/{resource['file_type']}")
    except Exception as e:
        return jsonify(success=False, error=f"Download failed: {e}"), 500

@resources_bp.route('/user', methods=['GET'])
def get_user_resources():
    try:
        department = request.args.get('department')
        level = request.args.get('level')
        if not department or not level:
            return jsonify(success=False, error="Department and level are required"), 400

        query = {'department': department, 'level': level}
        if category := request.args.get('category'):
            query['category'] = category

        page = max(1, int(request.args.get('page', 1)))
        limit = max(1, min(50, int(request.args.get('limit', 10))))
        skip = (page - 1) * limit

        resources = resources_collection.find(query).sort('created_at', DESCENDING).skip(skip).limit(limit)
        return jsonify(success=True, resources=[serialize_resource(r) for r in resources]), 200
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500

@resources_bp.route('/', methods=['GET'])
def get_all_resources():
    try:
        query = {}
        for key in ['department', 'level', 'category', 'file_type']:
            if val := request.args.get(key):
                query[key] = val
        if title := request.args.get('title'):
            query['title'] = {'$regex': title, '$options': 'i'}

        page = max(1, int(request.args.get('page', 1)))
        limit = max(1, min(100, int(request.args.get('limit', 20))))
        skip = (page - 1) * limit

        resources = resources_collection.find(query).sort('created_at', DESCENDING).skip(skip).limit(limit)
        return jsonify(success=True, resources=[serialize_resource(r) for r in resources]), 200
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500

@resources_bp.route('/<resource_id>', methods=['GET'])
def get_single_resource(resource_id):
    try:
        resource = resources_collection.find_one({'_id': ObjectId(resource_id)})
        if not resource:
            return jsonify(success=False, error='Not found'), 404
        return jsonify(success=True, resource=serialize_resource(resource)), 200
    except Exception as e:
        return jsonify(success=False, error='Invalid ID'), 400

@resources_bp.route('/<resource_id>', methods=['PUT'])
def update_resource(resource_id):
    try:
        resource = resources_collection.find_one({'_id': ObjectId(resource_id)})
        if not resource:
            return jsonify(success=False, error="Not found"), 404

        update_data = {}
        for key in ['title', 'category', 'level', 'department', 'file_type']:
            if val := request.form.get(key):
                update_data[key] = val

        file = request.files.get('file')
        if file:
            if resource.get('cloudinary_public_id'):
                cloudinary.uploader.destroy(resource['cloudinary_public_id'], invalidate=True)
            upload_result = cloudinary.uploader.upload(
                file,
                resource_type="auto",
                folder="naits_resources",
                use_filename=True,
                unique_filename=False
            )
            update_data.update({
                'file_url': upload_result.get('secure_url'),
                'cloudinary_public_id': upload_result.get('public_id'),
                'original_filename': secure_filename(file.filename),
                'file_type': request.form.get('file_type', resource['file_type'])
            })

        resources_collection.update_one({'_id': ObjectId(resource_id)}, {'$set': update_data})
        updated = resources_collection.find_one({'_id': ObjectId(resource_id)})
        return jsonify(success=True, resource=serialize_resource(updated)), 200
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500

@resources_bp.route('/<resource_id>', methods=['DELETE'])
def delete_resource(resource_id):
    try:
        resource = resources_collection.find_one({'_id': ObjectId(resource_id)})
        if not resource:
            return jsonify(success=False, error="Not found"), 404

        if resource.get('cloudinary_public_id'):
            cloudinary.uploader.destroy(resource['cloudinary_public_id'], invalidate=True)

        resources_collection.delete_one({'_id': ObjectId(resource_id)})
        return jsonify(success=True, message='Deleted successfully'), 200
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500

# ----------------- REGISTER BLUEPRINT ------------------
app.register_blueprint(resources_bp)

# ----------------- MAIN ------------------
if __name__ == '__main__':
    app.run(debug=True)
