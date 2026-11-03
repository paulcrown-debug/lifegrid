# LifeGrid Android App Packaging & Build Guide

This repository contains the configuration, assets, and Web App Manifest to package LifeGrid (`https://lifegrid-h6wgbnrcoinoedrcivbzb3.streamlit.app/`) into a native Android app (`.apk` for testing/sideloading and `.aab` for the Google Play Store).

---

## Option 1: Automatic 1-Click Online Build via PWABuilder (Fastest)

Microsoft's official open-source PWABuilder generates a ready-to-install Android APK in your web browser:

1. Open [PWABuilder.com](https://www.pwabuilder.com/) in your browser.
2. Enter your live URL:
   `https://lifegrid-h6wgbnrcoinoedrcivbzb3.streamlit.app/`
3. Click **Start**. PWABuilder will automatically read `static/manifest.json` and your icons.
4. Click **Package for Stores** -> **Android** -> **Generate**.
5. Download the `.zip` archive. It contains:
   - A signed test `.apk` file that you can install directly on your Android phone.
   - A production `.aab` bundle ready for the Google Play Console.

---

## Option 2: Google's Official Bubblewrap CLI (Professional TWA Build)

Google's Bubblewrap produces production-grade Trusted Web Activities (TWA) with zero browser address bar, custom splash screens, and native Android integration.

### Prerequisites
- Node.js (v16+) installed.
- Java JDK 17+ and Android SDK command-line tools (Bubblewrap can install these automatically).

### Build Commands

```bash
# 1. Install Google Bubblewrap CLI
npm install -g @bubblewrap/cli

# 2. In a clean folder, initialize from LifeGrid's live manifest:
bubblewrap init --manifest=https://lifegrid-h6wgbnrcoinoedrcivbzb3.streamlit.app/app/static/manifest.json

# (Or use the pre-configured twa-manifest.json from this repo):
# bubblewrap build

# 3. Build the APK & AAB
bubblewrap build
```

This generates:
- `app-release-signed.apk` (Install immediately on any phone)
- `app-release-bundle.aab` (Google Play Store release)

---

## Option 3: Native Android Studio WebView Project

If you prefer modifying native Java/Kotlin code in Android Studio:

1. Create a new "Empty Views Activity" project in Android Studio with package `com.lifegrid.app`.
2. Ensure `<uses-permission android:name="android.permission.INTERNET" />` is in `AndroidManifest.xml`.
3. In `MainActivity.kt`:
```kotlin
package com.lifegrid.app

import android.annotation.SuppressLint
import android.os.Bundle
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {
    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val webView = WebView(this)
        setContentView(webView)

        webView.webViewClient = WebViewClient()
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            cacheMode = WebSettings.LOAD_DEFAULT
            allowFileAccess = true
        }
        webView.loadUrl("https://lifegrid-h6wgbnrcoinoedrcivbzb3.streamlit.app/")
    }
}
```
4. Click **Build > Build APK(s)** in Android Studio.
