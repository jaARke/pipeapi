from reference_app.app import create_app
from reference_app.environment import read_settings

app = create_app(read_settings())
