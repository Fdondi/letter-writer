package io.github.fdondi.letterwriter.auth

import android.app.Activity
import android.app.PendingIntent
import android.content.Context
import androidx.credentials.CredentialManager
import androidx.credentials.CustomCredential
import androidx.credentials.GetCredentialRequest
import com.google.android.gms.auth.api.identity.AuthorizationRequest
import com.google.android.gms.auth.api.identity.AuthorizationResult
import com.google.android.gms.auth.api.identity.Identity
import com.google.android.gms.common.api.Scope
import com.google.android.libraries.identity.googleid.GetSignInWithGoogleOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import com.google.firebase.FirebaseApp
import com.google.firebase.auth.FirebaseAuth
import com.google.firebase.auth.FirebaseUser
import com.google.firebase.auth.GoogleAuthProvider
import com.google.firebase.firestore.FirebaseFirestore
import io.github.fdondi.letterwriter.BuildConfig
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.tasks.await

/** The signed-in Google account; [sub] is the desktop `user_id` and the `personal_data` doc id. */
data class SignedInUser(val sub: String, val email: String?, val displayName: String?)

sealed interface BigQueryAuth {
    data class Token(val accessToken: String) : BigQueryAuth

    /** The user has not granted the BigQuery scope yet; launch [intent] from an activity. */
    data class NeedsConsent(val intent: PendingIntent) : BigQueryAuth
}

class FirebaseNotConfiguredException(detail: String) : IllegalStateException(
    "Firebase is not configured for this build ($detail). Run scripts/firebase/setup_android_firebase.sh, then rebuild.",
)

class AuthManager(private val context: Context) {
    private val _user = MutableStateFlow<SignedInUser?>(null)
    val user: StateFlow<SignedInUser?> = _user.asStateFlow()

    /** Null when the build lacks google-services.json or the web client id. */
    val configurationProblem: String? = when {
        FirebaseApp.getApps(context).isEmpty() -> "app/app/google-services.json is missing"
        BuildConfig.WEB_CLIENT_ID.isBlank() -> "letterwriter.webClientId is missing from app/local.properties"
        else -> null
    }

    init {
        if (configurationProblem == null) {
            _user.value = FirebaseAuth.getInstance().currentUser
                ?.takeIf { u -> u.providerData.any { it.providerId == GoogleAuthProvider.PROVIDER_ID } }
                ?.let(::toSignedIn)
        }
    }

    fun firestore(): FirebaseFirestore {
        configurationProblem?.let { throw FirebaseNotConfiguredException(it) }
        return FirebaseFirestore.getInstance(FirebaseApp.getInstance(), BuildConfig.FIRESTORE_DATABASE)
    }

    fun requireUser(): SignedInUser = _user.value ?: throw IllegalStateException("Not signed in")

    suspend fun signIn(activity: Activity): SignedInUser {
        configurationProblem?.let { throw FirebaseNotConfiguredException(it) }
        val option = GetSignInWithGoogleOption.Builder(BuildConfig.WEB_CLIENT_ID).build()
        val request = GetCredentialRequest.Builder().addCredentialOption(option).build()
        val credential = CredentialManager.create(activity).getCredential(activity, request).credential
        if (credential !is CustomCredential || credential.type != GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL) {
            throw IllegalStateException("Unexpected credential type ${credential.type}; expected a Google ID token")
        }
        val idToken = GoogleIdTokenCredential.createFrom(credential.data).idToken
        val result = FirebaseAuth.getInstance()
            .signInWithCredential(GoogleAuthProvider.getCredential(idToken, null))
            .await()
        val firebaseUser = result.user ?: throw IllegalStateException("Firebase sign-in returned no user")
        return toSignedIn(firebaseUser).also { _user.value = it }
    }

    fun signOut() {
        if (configurationProblem == null) FirebaseAuth.getInstance().signOut()
        _user.value = null
    }

    /** OAuth access token for the BigQuery REST API, scoped to the signed-in Google account. */
    suspend fun bigQueryAuth(): BigQueryAuth {
        val request = AuthorizationRequest.builder()
            .setRequestedScopes(listOf(Scope(BIGQUERY_SCOPE)))
            .build()
        val result: AuthorizationResult = Identity.getAuthorizationClient(context).authorize(request).await()
        if (result.hasResolution()) {
            val intent = result.pendingIntent ?: throw IllegalStateException("BigQuery authorization needs consent but gave no intent")
            return BigQueryAuth.NeedsConsent(intent)
        }
        val token = result.accessToken ?: throw IllegalStateException("BigQuery authorization returned no access token")
        return BigQueryAuth.Token(token)
    }

    private fun toSignedIn(user: FirebaseUser): SignedInUser {
        val google = user.providerData.firstOrNull { it.providerId == GoogleAuthProvider.PROVIDER_ID }
            ?: throw IllegalStateException("Signed-in Firebase user has no Google identity")
        return SignedInUser(sub = google.uid, email = google.email ?: user.email, displayName = user.displayName)
    }

    companion object {
        const val BIGQUERY_SCOPE = "https://www.googleapis.com/auth/bigquery"
    }
}
