from app.core.database import Base, SessionLocal, engine
from app.core.security import get_password_hash
from app.models import User, WatchlistItem
from app.services.types import AssetType

Base.metadata.create_all(bind=engine)

db = SessionLocal()

try:
    if db.query(User).count() == 0:
        admin = User(
            username="admin",
            email="admin@example.com",
            hashed_password=get_password_hash("admin123"),
            full_name="管理员",
            is_active=1,
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)

        samples = [
            WatchlistItem(user_id=admin.id, symbol="000001", asset_type=AssetType.STOCK.value, name="平安银行"),
            WatchlistItem(user_id=admin.id, symbol="600519", asset_type=AssetType.STOCK.value, name="贵州茅台"),
            WatchlistItem(user_id=admin.id, symbol="510300", asset_type=AssetType.FUND.value, name="沪深300ETF"),
            WatchlistItem(user_id=admin.id, symbol="Au99.99", asset_type=AssetType.GOLD.value, name="黄金9999"),
        ]
        db.add_all(samples)
        db.commit()
        print("初始化数据成功！")
        print("默认账号: admin / admin123")
        print("示例自选: 平安银行、贵州茅台、沪深300ETF、黄金9999")
    else:
        print("数据库已有数据，跳过初始化")
except Exception as e:
    print(f"初始化数据时出错: {e}")
finally:
    db.close()
