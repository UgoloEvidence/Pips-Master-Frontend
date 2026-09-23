import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
k=ec.generate_private_key(ec.SECP256R1())
pub=k.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
priv=k.private_numbers().private_value.to_bytes(32,'big')
print('PMA_VAPID_PUBLIC_KEY='+base64.urlsafe_b64encode(pub).rstrip(b'=').decode())
print('PMA_VAPID_PRIVATE_KEY='+base64.urlsafe_b64encode(priv).rstrip(b'=').decode())
