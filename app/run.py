from app import create_app
app = create_app()  # production/development

if __name__ == '__main__':
    app.run(debug=False, port=8008, host='0.0.0.0', threaded=True)
