#!/usr/bin/env bash
# Print the latest release version of each library the Android app depends on (read-only).
set -uo pipefail

central() { # group artifact
  curl -s "https://repo1.maven.org/maven2/${1//.//}/$2/maven-metadata.xml" | grep -o '<release>[^<]*' | sed 's/<release>//'
}
google() { # group artifact
  curl -s "https://dl.google.com/android/maven2/${1//.//}/$2/maven-metadata.xml" | grep -o '<release>[^<]*' | sed 's/<release>//'
}

while read -r repo group artifact; do
  [ -z "$repo" ] && continue
  printf '%-60s %s\n' "$group:$artifact" "$($repo "$group" "$artifact")"
done <<'EOF'
central org.jetbrains.kotlinx kotlinx-serialization-json
central org.jetbrains.kotlinx kotlinx-coroutines-android
central org.jetbrains.kotlinx kotlinx-coroutines-play-services
central org.jetbrains.kotlinx kotlinx-coroutines-test
central com.squareup.okhttp3 okhttp
central com.squareup.okhttp3 mockwebserver
central org.jsoup jsoup
central org.jetbrains.kotlin kotlin-serialization
google com.google.firebase firebase-bom
google com.google.gms google-services
google androidx.credentials credentials
google androidx.credentials credentials-play-services-auth
google com.google.android.libraries.identity.googleid googleid
google com.google.android.gms play-services-auth
google androidx.datastore datastore-preferences
google androidx.navigation navigation-compose
google androidx.lifecycle lifecycle-viewmodel-compose
google androidx.lifecycle lifecycle-runtime-ktx
google androidx.lifecycle lifecycle-process
google androidx.activity activity-compose
google androidx.core core-ktx
google androidx.compose.material material-icons-extended
google androidx.compose compose-bom
EOF
