from unittest.mock import Mock

m = Mock(value="abc")
print(f"Type of m.value: {type(m.value)}")
print(f"Value of m.value: {m.value}")

try:
    int(m.value)
except ValueError:
    print("ValueError raised as expected")
except Exception as e:
    print(f"Unexpected exception: {type(e).__name__}: {e}")
