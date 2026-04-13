from school_admin.media import with_logo_cache_bust
import time

def test_cache_bust():
    logo_path = "/media/logo-uuid123.png"
    
    # 1. Test with /media/ URL
    busted_url = with_logo_cache_bust(logo_path)
    print(f"Original: {logo_path}")
    print(f"Busted:   {busted_url}")
    assert busted_url.startswith("/media/logo-uuid123.png?v=")
    
    # 2. Test re-stamping
    time.sleep(1.1)
    rebusted_url = with_logo_cache_bust(busted_url)
    print(f"Re-busted: {rebusted_url}")
    assert rebusted_url != busted_url
    assert "?v=" in rebusted_url
    assert rebusted_url.count("?v=") == 1
    
    # 3. Test static URL
    static_url = "/static/logo.svg"
    busted_static = with_logo_cache_bust(static_url)
    print(f"Static Busted: {busted_static}")
    assert busted_static.startswith("/static/logo.svg?v=")
    
    print("\nCache busting verification successful!")

if __name__ == "__main__":
    test_cache_bust()
