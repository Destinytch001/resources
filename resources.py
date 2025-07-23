import datetime
import os
from flask import Flask, Blueprint, request, jsonify, send_file
from flask_pymongo import PyMongo
from flask_cors import CORS
from bson import ObjectId
from pymongo import DESCENDING
import cloudinary
import cloudinary.uploader
import requests
from io import BytesIO
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- App & DB Setup ---
app = Flask(__name__)
CORS(app)

# MongoDB configuration
app.config["MONGO_URI"] = os.getenv("MONGO_URI", "mongodb://localhost:27017/naits_db")
db = PyMongo(app).db

# Cloudinary config (⚠️ stored securely via .env)
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

# --- Blueprint Setup ---
resources_bp = Blueprint('resources_bp', __name__, url_prefix='/api/resources')
resources_collection = db.resources


# --- Helpers ---
def serialize_resource(res):
    res['_id'] = str(res['_id'])
    return res

def get_file_extension(file_type):
    """Map file type to extension"""
    file_type = file_type.lower()
    return {
        'pdf': '.pdf',
        'doc': '.doc',
        'mp3': '.mp3',
        'mp4': '.mp4',
        'img': '.jpg'
    }.get(file_type, '')

def download_and_convert(url, original_filename, file_type):
    try:
        response = requests.get(url)
        response.raise_for_status()
        file_data = BytesIO(response.content)
        filename = secure_filename(original_filename)
        base, ext = os.path.splitext(filename)
        if not ext or ext.lower() != get_file_extension(file_type):
            ext = get_file_extension(file_type)
            filename = f"{base}{ext}"
        return file_data, filename
    except Exception as e:
        print(f"Download error: {e}")
        raise

# -----------------------------
# ✅ Upload New Resource
# -----------------------------
@resources_bp.route('/upload', methods=['POST'])
def upload_resource():
    try:
        required_fields = ['title', 'level', 'department', 'category', 'file_type']
        form_data = {field: request.form.get(field) for field in required_fields}
        file = request.files.get('file')
        if None in form_data.values() or not file:
            return jsonify(success=False, error="All fields are required"), 400

        upload_result = cloudinary.uploader.upload(
            file,
            resource_type="auto",
            folder="naits_resources",
            use_filename=True,
            unique_filename=False
        )
        if not upload_result.get("secure_url"):
            return jsonify(success=False, error="Cloudinary upload failed"), 500

        new_resource = {
            'title': form_data['title'],
            'file_url': upload_result["secure_url"],
            'file_type': form_data['file_type'].lower(),
            'level': form_data['level'],
            'department': form_data['department'],
            'category': form_data['category'],
            'created_at': datetime.datetime.utcnow(),
            'cloudinary_public_id': upload_result.get('public_id'),
            'original_filename': secure_filename(file.filename)
        }

        inserted = resources_collection.insert_one(new_resource)
        new_resource['_id'] = str(inserted.inserted_id)
        return jsonify(success=True, resource=new_resource), 201

    except Exception as e:
        print(f"Upload Error: {e}")
        return jsonify(success=False, error="Something went wrong during upload"), 500

# -----------------------------
# ✅ Download Resource
# -----------------------------
@resources_bp.route('/download/<resource_id>', methods=['GET'])
def download_resource(resource_id):
    try:
        resource = resources_collection.find_one({'_id': ObjectId(resource_id)})
        if not resource:
            return jsonify(success=False, error='Resource not found'), 404

        file_data, filename = download_and_convert(
            resource['file_url'],
            resource.get('original_filename', resource['title']),
            resource['file_type']
        )

        return send_file(
            file_data,
            as_attachment=True,
            download_name=filename,
            mimetype=f"application/{resource['file_type']}"
        )

    except Exception as e:
        print(f"Download Error: {e}")
        return jsonify(success=False, error="Failed to download resource"), 500

# -----------------------------
# ✅ Get Resources for User
# -----------------------------
@resources_bp.route('/user', methods=['GET'])
def get_user_resources():
    try:
        department = request.args.get('department')
        level = request.args.get('level')
        if not department or not level:
            return jsonify(success=False, error="Department and level are required"), 400

        query = {'department': department, 'level': level}
        if request.args.get('category'):
            query['category'] = request.args.get('category')

        page = max(1, int(request.args.get('page', 1)))
        limit = max(1, min(50, int(request.args.get('limit', 10))))
        skip = (page - 1) * limit

        cursor = resources_collection.find(query)\
            .sort('created_at', DESCENDING)\
            .skip(skip).limit(limit)

        resources = [serialize_resource(r) for r in cursor]
        return jsonify(success=True, resources=resources), 200

    except Exception as e:
        print(f"User Resource Error: {e}")
        return jsonify(success=False, error="Failed to fetch user resources"), 500

# -----------------------------
# ✅ Admin: Get All Resources
# -----------------------------
@resources_bp.route('/', methods=['GET'])
def get_all_resources():
    try:
        query = {}
        for key in ['department', 'level', 'category', 'file_type']:
            if value := request.args.get(key):
                query[key] = value
        if title := request.args.get('title'):
            query['title'] = {'$regex': title, '$options': 'i'}

        page = max(1, int(request.args.get('page', 1)))
        limit = max(1, min(100, int(request.args.get('limit', 20))))
        skip = (page - 1) * limit

        cursor = resources_collection.find(query)\
            .sort('created_at', DESCENDING)\
            .skip(skip).limit(limit)

        resources = [serialize_resource(r) for r in cursor]
        return jsonify(success=True, resources=resources), 200

    except Exception as e:
        print(f"Get All Error: {e}")
        return jsonify(success=False, error="Failed to load resources"), 500

# -----------------------------
# ✅ Get Single Resource
# -----------------------------
@resources_bp.route('/<resource_id>', methods=['GET'])
def get_single_resource(resource_id):
    try:
        resource = resources_collection.find_one({'_id': ObjectId(resource_id)})
        if not resource:
            return jsonify(success=False, error='Resource not found'), 404
        return jsonify(success=True, resource=serialize_resource(resource)), 200
    except Exception as e:
        print(f"Get Single Error: {e}")
        return jsonify(success=False, error='Invalid resource ID'), 400

# -----------------------------
# ✅ Update Resource
# -----------------------------
@resources_bp.route('/<resource_id>', methods=['PUT'])
def update_resource(resource_id):
    try:
        resource = resources_collection.find_one({'_id': ObjectId(resource_id)})
        if not resource:
            return jsonify(success=False, error="Resource not found"), 404

        update_data = {}
        for key in ['title', 'category', 'level', 'department', 'file_type']:
            if value := request.form.get(key):
                update_data[key] = value

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

        resources_collection.update_one(
            {'_id': ObjectId(resource_id)},
            {'$set': update_data}
        )

        updated = resources_collection.find_one({'_id': ObjectId(resource_id)})
        return jsonify(success=True, resource=serialize_resource(updated)), 200

    except Exception as e:
        print(f"Update Error: {e}")
        return jsonify(success=False, error="Failed to update resource"), 500

# -----------------------------
# ✅ Delete Resource
# -----------------------------
@resources_bp.route('/<resource_id>', methods=['DELETE'])
def delete_resource(resource_id):
    try:
        resource = resources_collection.find_one({'_id': ObjectId(resource_id)})
        if not resource:
            return jsonify(success=False, error="Resource not found"), 404

        if resource.get('cloudinary_public_id'):
            cloudinary.uploader.destroy(resource['cloudinary_public_id'], invalidate=True)

        resources_collection.delete_one({'_id': ObjectId(resource_id)})
        return jsonify(success=True, message='Resource deleted successfully'), 200

    except Exception as e:
        print(f"Delete Error: {e}")
        return jsonify(success=False, error="Failed to delete resource"), 500


# -----------------------------
# ✅ Run Standalone Server (Development)
# -----------------------------
if __name__ == '__main__':
    app.register_blueprint(resources_bp)
    
    # Enable debug mode only in development
    app.config["ENV"] = "development"
    app.config["DEBUG"] = True

    app.run(host='0.0.0.0', port=5000, debug=True)
