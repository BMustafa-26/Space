package com.example.spaceclient

import android.net.Uri
import android.os.Bundle
import android.view.MotionEvent
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import androidx.appcompat.app.AppCompatActivity
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.exoplayer.DefaultLoadControl
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.ProgressiveMediaSource
import androidx.media3.ui.PlayerView
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress

private const val VIDEO_PORT = 5000
private const val INPUT_PORT = 5001

/**
 * Android LAN mirror client skeleton.
 *
 * - The connection panel collects the Linux PC IP address.
 * - ExoPlayer/MediaCodec renders the incoming FFmpeg H.264 MPEG-TS UDP stream.
 * - Touch events are converted into "X,Y,ACTION" UDP datagrams for the PC server.
 */
class MainActivity : AppCompatActivity() {
    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    private lateinit var root: FrameLayout
    private lateinit var connectionPanel: LinearLayout
    private lateinit var ipEditText: EditText
    private lateinit var playerView: PlayerView
    private var player: ExoPlayer? = null
    private var touchController: TouchController? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        buildUi()
    }

    private fun buildUi() {
        root = FrameLayout(this)
        playerView = PlayerView(this).apply {
            useController = false
            visibility = View.GONE
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT,
            )
        }

        ipEditText = EditText(this).apply {
            hint = "PC IP address, e.g. 192.168.1.10"
            setSingleLine(true)
        }
        val connectButton = Button(this).apply {
            text = "Bağlan"
            setOnClickListener {
                val pcIp = ipEditText.text.toString().trim()
                if (pcIp.isNotEmpty()) connect(pcIp)
            }
        }
        connectionPanel = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 48, 48, 48)
            addView(ipEditText)
            addView(connectButton)
        }

        root.addView(playerView)
        root.addView(connectionPanel)
        setContentView(root)
    }

    private fun connect(pcIp: String) {
        connectionPanel.visibility = View.GONE
        playerView.visibility = View.VISIBLE
        enterImmersiveFullscreen()

        touchController = TouchController(pcIp, INPUT_PORT)
        startUdpVideo(pcIp)
    }

    private fun startUdpVideo(pcIp: String) {
        // The Linux server pushes to udp://ANDROID_IP:5000. Android binds/listens on local port 5000.
        // ExoPlayer uses platform MediaCodec where available for hardware H.264 decoding.
        val uri = Uri.parse("udp://0.0.0.0:$VIDEO_PORT")
        val mediaItem = MediaItem.fromUri(uri)
        val mediaSource = ProgressiveMediaSource.Factory(DefaultDataSource.Factory(this))
            .createMediaSource(mediaItem)

        player = ExoPlayer.Builder(this)
            .setLoadControl(
                DefaultLoadControl.Builder()
                    .setBufferDurationsMs(
                        100,  // minBufferMs: keep tiny for low latency
                        500,  // maxBufferMs
                        50,   // bufferForPlaybackMs
                        100,  // bufferForPlaybackAfterRebufferMs
                    )
                    .build(),
            )
            .build()
            .also { exoPlayer ->
                exoPlayer.addListener(object : Player.Listener {
                    override fun onPlayerError(error: PlaybackException) {
                        // Keep the skeleton simple: production code should retry and show diagnostics.
                        error.printStackTrace()
                    }
                })
                playerView.player = exoPlayer
                exoPlayer.setMediaSource(mediaSource)
                exoPlayer.prepare()
                exoPlayer.playWhenReady = true
            }
    }

    override fun dispatchTouchEvent(event: MotionEvent): Boolean {
        if (playerView.visibility == View.VISIBLE) {
            val action = when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> "DOWN"
                MotionEvent.ACTION_MOVE -> "MOVE"
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> "UP"
                else -> null
            }
            if (action != null) {
                touchController?.send(event.x, event.y, action)
                return true
            }
        }
        return super.dispatchTouchEvent(event)
    }

    private fun enterImmersiveFullscreen() {
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.R) {
            window.insetsController?.let { controller ->
                controller.hide(WindowInsets.Type.statusBars() or WindowInsets.Type.navigationBars())
                controller.systemBarsBehavior = WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            }
        } else {
            @Suppress("DEPRECATION")
            window.decorView.systemUiVisibility =
                View.SYSTEM_UI_FLAG_FULLSCREEN or
                    View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
                    View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY or
                    View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or
                    View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION or
                    View.SYSTEM_UI_FLAG_LAYOUT_STABLE
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        player?.release()
        appScope.cancel()
    }

    /** Sends touch coordinates to the Linux server without blocking the UI thread. */
    inner class TouchController(
        private val pcIp: String,
        private val inputPort: Int,
    ) {
        fun send(x: Float, y: Float, action: String) {
            appScope.launch(Dispatchers.IO) {
                try {
                    val payload = "${x.toInt()},${y.toInt()},$action".toByteArray(Charsets.UTF_8)
                    DatagramSocket().use { socket ->
                        val packet = DatagramPacket(
                            payload,
                            payload.size,
                            InetAddress.getByName(pcIp),
                            inputPort,
                        )
                        socket.send(packet)
                    }
                } catch (exception: Exception) {
                    // Do not crash the UI if Wi-Fi drops or the server is unavailable.
                    exception.printStackTrace()
                }
            }
        }
    }
}
