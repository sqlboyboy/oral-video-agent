package com.jiesu.oral_video_agent_client

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.core.content.FileProvider
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.nio.charset.StandardCharsets
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class MainActivity : FlutterActivity() {
    private val platformChannel = "com.jiesu.oral_video_agent_client/updater"
    private val securePreferencesName = "jiesu_secure_cloud_auth_v1"
    private val secureKeyAlias = "jiesu_cloud_auth_keystore_key_v1"
    private val allowedSecureKeys = setOf(
        "cloud_activation_token_v1",
        "cloud_device_token_v1",
    )

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            platformChannel,
        ).setMethodCallHandler { call, result ->
            when (call.method) {
                "readSecureValue" -> {
                    val key = call.argument<String>("key")
                    if (key == null || key !in allowedSecureKeys) {
                        result.error("invalid_key", "安全存储键不受支持", null)
                        return@setMethodCallHandler
                    }
                    result.success(readSecureValue(key))
                }

                "writeSecureValue" -> {
                    val key = call.argument<String>("key")
                    val value = call.argument<String>("value")
                    if (key == null || key !in allowedSecureKeys) {
                        result.error("invalid_key", "安全存储键不受支持", null)
                        return@setMethodCallHandler
                    }
                    if (value.isNullOrEmpty()) {
                        result.error("invalid_value", "安全存储值不能为空", null)
                        return@setMethodCallHandler
                    }
                    try {
                        writeSecureValue(key, value)
                        result.success(null)
                    } catch (error: Exception) {
                        result.error("secure_storage_failed", error.message, null)
                    }
                }

                "deleteSecureValue" -> {
                    val key = call.argument<String>("key")
                    if (key == null || key !in allowedSecureKeys) {
                        result.error("invalid_key", "安全存储键不受支持", null)
                        return@setMethodCallHandler
                    }
                    securePreferences().edit().remove(key).apply()
                    result.success(null)
                }

                "canRequestPackageInstalls" -> {
                    result.success(canRequestPackageInstalls())
                }

                "openInstallPermission" -> {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                        val intent = Intent(
                            Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                            Uri.parse("package:$packageName"),
                        )
                        startActivity(intent)
                    }
                    result.success(null)
                }

                "installApk" -> {
                    val path = call.argument<String>("path")
                    if (path.isNullOrBlank()) {
                        result.error("invalid_path", "安装包路径为空", null)
                        return@setMethodCallHandler
                    }
                    if (!canRequestPackageInstalls()) {
                        result.error("permission_required", "尚未允许安装未知应用", null)
                        return@setMethodCallHandler
                    }
                    try {
                        val apkFile = File(path).canonicalFile
                        val updateDir = File(cacheDir, "updates").canonicalFile
                        val allowedPrefix = updateDir.path + File.separator
                        if (
                            !apkFile.isFile ||
                            !apkFile.path.startsWith(allowedPrefix) ||
                            !apkFile.name.endsWith(".apk", ignoreCase = true)
                        ) {
                            result.error("invalid_path", "安装包路径不安全或文件不存在", null)
                            return@setMethodCallHandler
                        }
                        val apkUri = FileProvider.getUriForFile(
                            this,
                            "$packageName.fileprovider",
                            apkFile,
                        )
                        val intent = Intent(Intent.ACTION_VIEW).apply {
                            setDataAndType(
                                apkUri,
                                "application/vnd.android.package-archive",
                            )
                            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                        }
                        startActivity(intent)
                        result.success(null)
                    } catch (error: Exception) {
                        result.error("install_failed", error.message, null)
                    }
                }

                else -> result.notImplemented()
            }
        }
    }

    private fun canRequestPackageInstalls(): Boolean {
        return Build.VERSION.SDK_INT < Build.VERSION_CODES.O ||
            packageManager.canRequestPackageInstalls()
    }

    private fun securePreferences() =
        getSharedPreferences(securePreferencesName, MODE_PRIVATE)

    private fun getOrCreateSecretKey(): SecretKey {
        val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        val existingKey = keyStore.getKey(secureKeyAlias, null) as? SecretKey
        if (existingKey != null) return existingKey

        val keyGenerator = KeyGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_AES,
            "AndroidKeyStore",
        )
        val specification = KeyGenParameterSpec.Builder(
            secureKeyAlias,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
        )
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setRandomizedEncryptionRequired(true)
            .build()
        keyGenerator.init(specification)
        return keyGenerator.generateKey()
    }

    private fun writeSecureValue(key: String, value: String) {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateSecretKey())
        val encrypted = cipher.doFinal(value.toByteArray(StandardCharsets.UTF_8))
        val payload = listOf(cipher.iv, encrypted).joinToString(":") {
            Base64.encodeToString(it, Base64.NO_WRAP)
        }
        securePreferences().edit().putString(key, payload).apply()
    }

    private fun readSecureValue(key: String): String? {
        val payload = securePreferences().getString(key, null) ?: return null
        return try {
            val parts = payload.split(":", limit = 2)
            require(parts.size == 2)
            val iv = Base64.decode(parts[0], Base64.NO_WRAP)
            val encrypted = Base64.decode(parts[1], Base64.NO_WRAP)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(
                Cipher.DECRYPT_MODE,
                getOrCreateSecretKey(),
                GCMParameterSpec(128, iv),
            )
            String(cipher.doFinal(encrypted), StandardCharsets.UTF_8)
        } catch (_: Exception) {
            securePreferences().edit().remove(key).apply()
            null
        }
    }
}
