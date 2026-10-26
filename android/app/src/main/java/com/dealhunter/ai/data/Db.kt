package com.dealhunter.ai.data

import android.content.Context
import androidx.room.ColumnInfo
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import kotlinx.coroutines.flow.Flow

object SyncState {
    const val PENDING = "pending_add"   // guardado en el teléfono, aún no enviado al servidor
    const val SYNCED = "synced"
    const val FAILED = "failed"         // el servidor lo rechazó (enlace inválido, límite del plan…)
}

/** Elemento del carrito guardado localmente. `json` guarda el último TrackedDto completo del servidor. */
@Entity(tableName = "cart")
data class CartEntity(
    @PrimaryKey(autoGenerate = true) val localId: Long = 0,
    @ColumnInfo(index = true) val remoteId: Long? = null,
    val url: String,
    val urlKey: String,
    val title: String? = null,
    val storeName: String? = null,
    val syncState: String = SyncState.PENDING,
    val syncError: String? = null,
    val attempts: Int = 0,
    val createdAt: Long = System.currentTimeMillis(),
    val archived: Boolean = false,
    val purchased: Boolean = false,
    val json: String? = null,
) {
    val dto: TrackedDto? get() = json?.let { runCatching { AppJson.decodeFromString<TrackedDto>(it) }.getOrNull() }
}

@Dao
interface CartDao {
    @Query("SELECT * FROM cart ORDER BY createdAt DESC")
    fun observeAll(): Flow<List<CartEntity>>

    @Query("SELECT * FROM cart WHERE localId = :id")
    suspend fun byLocalId(id: Long): CartEntity?

    @Query("SELECT * FROM cart WHERE localId = :id")
    fun observe(id: Long): Flow<CartEntity?>

    @Query("SELECT * FROM cart WHERE remoteId = :remoteId LIMIT 1")
    suspend fun byRemoteId(remoteId: Long): CartEntity?

    @Query("SELECT * FROM cart WHERE urlKey = :key LIMIT 1")
    suspend fun byUrlKey(key: String): CartEntity?

    @Query("SELECT * FROM cart WHERE syncState = 'pending_add' ORDER BY createdAt")
    suspend fun pending(): List<CartEntity>

    @Query("SELECT COUNT(*) FROM cart WHERE syncState = 'pending_add'")
    fun pendingCount(): Flow<Int>

    @Query("SELECT * FROM cart")
    suspend fun all(): List<CartEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(e: CartEntity): Long

    @Query("DELETE FROM cart WHERE localId = :id")
    suspend fun delete(id: Long)

    @Query("DELETE FROM cart")
    suspend fun clear()
}

@Database(entities = [CartEntity::class], version = 1, exportSchema = false)
abstract class AppDb : RoomDatabase() {
    abstract fun cart(): CartDao

    companion object {
        fun create(ctx: Context): AppDb =
            Room.databaseBuilder(ctx, AppDb::class.java, "dealhunter.db").fallbackToDestructiveMigration().build()
    }
}
