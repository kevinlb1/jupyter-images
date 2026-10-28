# Hub for ci/hub-compat.sh: the deployed JupyterHub version, spawning the
# locally built image under test as a named server through DockerSpawner.
import os

c = get_config()  # noqa: F821

c.JupyterHub.authenticator_class = "dummy"
c.Authenticator.allow_all = True
c.JupyterHub.allow_named_servers = True

c.JupyterHub.spawner_class = "dockerspawner.DockerSpawner"
c.DockerSpawner.network_name = os.environ["HUB_COMPAT_NETWORK"]
c.DockerSpawner.image = os.environ["HUB_COMPAT_IMAGE"]
c.DockerSpawner.remove = True
# Start the server the way Z2JH does (its singleuser.cmd default) rather than
# with the image's own CMD: rocker's /init would start RStudio as a service.
c.DockerSpawner.cmd = ["jupyterhub-singleuser"]
# Same per-spawn variable the deployed hub sets for nbgrader.
c.DockerSpawner.environment = {"NBGRADER_COURSE_ID": "hub-compat-course"}
c.Spawner.start_timeout = 300
c.Spawner.http_timeout = 300

c.JupyterHub.hub_ip = "0.0.0.0"
c.JupyterHub.hub_connect_ip = os.environ["HUB_COMPAT_HUB_NAME"]

c.JupyterHub.services = [{"name": "tester", "api_token": os.environ["TESTER_TOKEN"]}]
c.JupyterHub.load_roles = [{
    "name": "tester",
    "scopes": ["admin:users", "admin:servers", "access:servers", "read:users"],
    "services": ["tester"],
}]
