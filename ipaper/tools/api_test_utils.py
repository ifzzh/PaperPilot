"""
API test utilities for testing LLM and MinerU connections
"""

import requests

from ipaper.security.outbound import OutboundPolicy, OutboundPolicyError, guarded_request


def create_openai_client(api_key: str, base_url: str, outbound_policy: OutboundPolicy):
    from openai import DefaultHttpxClient, OpenAI

    outbound_policy.validate(base_url, purpose="ai")
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=30.0,
        http_client=DefaultHttpxClient(follow_redirects=False),
    )


def test_llm_api(
    model: str,
    base_url: str,
    api_key: str,
    outbound_policy: OutboundPolicy | None = None,
) -> tuple[bool, str]:
    """
    Test LLM API connection

    Args:
        model: Model name
        base_url: Base URL
        api_key: API key

    Returns:
        (success, error_message)
    """
    try:
        if outbound_policy is None:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=base_url)
        else:
            client = create_openai_client(api_key, base_url, outbound_policy)

        # Try a simple completion with the configured model. Some OpenAI-compatible
        # services support chat completions but return an empty /models list.
        response = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": "Hi"}], max_tokens=10
        )

        if response.choices and response.choices[0].message:
            return True, "Connection successful"
        else:
            return False, "No valid response"

    except OutboundPolicyError as exc:
        return False, exc.reason
    except Exception:
        return False, "llm_connection_failed"


def test_mineru_api(
    server_url: str, outbound_policy: OutboundPolicy | None = None
) -> tuple[bool, str]:
    """
    Test MinerU local server connection

    Args:
        server_url: MinerU server URL

    Returns:
        (success, error_message)
    """
    try:
        # Test health endpoint
        test_url = f"{server_url.rstrip('/')}/health"
        if outbound_policy is not None:
            response = guarded_request(
                outbound_policy, "GET", test_url, purpose="ai", timeout=10
            )
        else:
            response = requests.get(test_url, timeout=10, allow_redirects=False)

        if response.status_code == 200:
            return True, "MinerU server is accessible"
        else:
            return False, f"Server returned status {response.status_code}"

    except requests.exceptions.ConnectionError:
        return False, "mineru_connection_failed"
    except requests.exceptions.Timeout:
        return False, "Connection timeout"
    except OutboundPolicyError as exc:
        return False, exc.reason
    except Exception:
        return False, "mineru_connection_failed"


def test_mineru_api_token(api_token: str) -> tuple[bool, str]:
    """
    Test MinerU API token validity

    Args:
        api_token: MinerU API token

    Returns:
        (success, error_message)
    """
    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_token}",
        }

        # Try a simple API call (request upload links with a dummy file)
        # Using a dummy file name to test token validity without actually uploading
        response = requests.post(
            "https://mineru.net/api/v4/file-urls/batch",
            headers=headers,
            json={
                "files": [{"name": "test.pdf", "data_id": "test"}],
                "model_version": "vlm",
            },
            timeout=10,
            allow_redirects=False,
        )

        if response.status_code == 200:
            result = response.json()
            if result.get("code") == 0:
                return True, "API token is valid"
            else:
                # If we get a business logic error, it means the token is valid
                # but the request parameters might be wrong (e.g., file doesn't exist)
                # This is still a success for token validation purposes
                error_msg = result.get("msg", "Unknown error")
                return True, f"API token is valid (Note: {error_msg})"
        elif response.status_code == 401:
            return False, "Invalid API token or authentication failed"
        elif response.status_code == 403:
            return False, "Access forbidden - check your token permissions"
        else:
            return False, "mineru_api_rejected"

    except requests.exceptions.ConnectionError:
        return False, "Cannot connect to MinerU API server"
    except requests.exceptions.Timeout:
        return False, "Connection timeout"
    except Exception:
        return False, "mineru_api_connection_failed"
